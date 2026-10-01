"""The conclusion and the footnote of a content slide set on a template sample.

A composed slide reserves their room before the content; a sample slide has its own geometry, so they go into the
room the sample leaves under its content: the conclusion as the composer sets it (a strip of the template's card
colour with an accent bar, or the bar and the line on the bare ground), the footnote as small print at the foot. When
the sample leaves no room the slide is not shown on that sample (the renderer tries another one, then composes)."""

from __future__ import annotations

from typing import Optional

from lxml import etree

from verstka.analysis.xmlns import q
from verstka.rendering.deck import element_bbox
from verstka.schemas.common import Bbox
from verstka.schemas.outline import DeckOutline, OutlineSlide
from verstka.schemas.common import SlotRole
from verstka.schemas.template import Pattern, TemplateManifest

_DRAWN = ("sp", "pic", "graphicFrame", "grpSp", "cxnSp")


def _paints(el) -> bool:
    """A shape that shows something: text, a fill, a line or a picture fill."""
    if "".join(t.text or "" for t in el.iter(q("a:t"))).strip():
        return True
    spPr = el.find(q("p:spPr"))
    if spPr is None:
        return False
    if any(spPr.find(q(x)) is not None for x in ("a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill")):
        return True
    ln = spPr.find(q("a:ln"))
    if ln is not None and ln.find(q("a:noFill")) is None and any(ln.find(q(x)) is not None for x in ("a:solidFill", "a:gradFill")):
        return True
    style = el.find(q("p:style"))
    if style is not None and spPr.find(q("a:noFill")) is None:
        ref = style.find(q("a:fillRef"))
        if ref is not None and (ref.get("idx") or "0") != "0":
            return True
    return False


def _content_extent(slide, pattern: Pattern, W: int, H: int) -> Optional[tuple[int, int, int]]:
    """(left, right, bottom) of what the slide shows, its chrome, full-slide grounds and the marks at its foot aside."""
    chrome = set(pattern.chrome_shape_ids)
    tree = slide._element.cSld.find(q("p:spTree"))
    left, right, bottom = None, None, None
    for el in tree:
        if etree.QName(el).localname not in _DRAWN:
            continue
        nv = el.find(".//" + q("p:cNvPr"))
        if nv is not None and nv.get("id") in chrome:
            continue
        b = element_bbox(el)
        if not b or b[2] <= 0 or b[3] <= 0 or b[2] * b[3] >= 0.9 * W * H:
            continue
        if etree.QName(el).localname == "sp" and not _paints(el):
            continue  # an empty box that draws nothing (an export's invisible frame)
        if b[1] >= 0.8 * H and b[3] <= 0.15 * H and b[2] * b[3] < 0.2 * W * H:
            continue  # a logo, a page number at the foot
        left = b[0] if left is None else min(left, b[0])
        right = b[0] + b[2] if right is None else max(right, b[0] + b[2])
        bottom = b[1] + b[3] if bottom is None else max(bottom, b[1] + b[3])
    if left is None:
        return None
    return left, right, bottom


def _cut_rules(slide, box: Bbox, gap: int, W: int, H: int) -> None:
    """A vertical rule of the sample that would run through the conclusion (Dark Minimalist p16: the divider between
    the text and the figures down to the foot) ends a gap above it."""
    from verstka.rendering.deck import set_element_pos

    tree = slide._element.cSld.find(q("p:spTree"))
    for el in list(tree):
        tag = etree.QName(el).localname
        if tag not in ("cxnSp", "sp", "pic"):
            continue
        b = element_bbox(el)
        if not b or b[2] > 0.006 * W or b[3] < 0.1 * H:
            continue
        if tag == "sp" and "".join(t.text or "" for t in el.iter(q("a:t"))).strip():
            continue
        if b[0] + b[2] < box.x or b[0] > box.x2 or b[1] + b[3] <= box.y or b[1] >= box.y2:
            continue
        new_h = box.y - gap - b[1]
        if new_h >= 0.08 * H:
            set_element_pos(el, h=new_h)


def _free_stretch(arts: list, x0: int, x1: int, y0: int, y1: int, gap: int) -> Optional[tuple[int, int]]:
    """The widest stretch of [x0, x1] that no art box standing in the band [y0, y1] covers (a gap kept from it)."""
    blocks = sorted((max(a.x - gap, x0), min(a.x + a.w + gap, x1)) for a in arts if a.y < y1 and a.y + a.h > y0 and a.x < x1 and a.x + a.w > x0)
    if not blocks:
        return None
    best, cur = None, x0
    for b0, b1 in blocks:
        if b0 > cur and (best is None or b0 - cur > best[1] - best[0]):
            best = (cur, b0)
        cur = max(cur, b1)
    if x1 > cur and (best is None or x1 - cur > best[1] - best[0]):
        best = (cur, x1)
    return best or (x0, x0)


def _composer(builder, slide, oslide: OutlineSlide, outline: DeckOutline, manifest: TemplateManifest, pattern: Pattern, probe: Bbox):
    """A composer on the ground under `probe`, with the template's card for the conclusion strip."""
    from verstka.rendering.compose import Composer, Kit
    from verstka.rendering.synth import _card_proto, _ground_at

    W, H = builder.slide_w, builder.slide_h
    ground = _ground_at(slide, probe) or manifest.tokens.color_for("background.dark" if pattern.family.value == "dark" else "background.light") or "FFFFFF"
    proto = _card_proto(builder, manifest, pattern.family, ground)
    kit = Kit(manifest, W, H, ground, card_proto=proto[0] if proto else None)
    if proto:
        kit.card.fill, kit.card.line = proto[1], proto[2]
        kit.card.colors = kit.colors_on(proto[1] or ground, inside_card=bool(proto[1]))
    return Composer(slide, kit, oslide, outline, outline.strategy or "structured", manifest), kit


def notes_need(builder, slide, oslide: OutlineSlide, outline: DeckOutline, manifest: TemplateManifest, pattern: Pattern) -> tuple[int, int]:
    """(height, floor) in EMU: the room the slide's conclusion and footnote take at the foot of a sample — the strip
    at the deck's one size over most of the content width, its gap, the footnote — and the line they stand on (the
    safe area's foot, above a footer). The renderer keeps it free while it sets the sample's content (0, floor when
    there is nothing to set)."""
    from verstka.rendering.synth import _content_bottom_limit

    W, H = builder.slide_w, builder.slide_h
    safe = manifest.tokens.spacing.safe_area
    floor = _content_bottom_limit(slide, int(safe.y2 * H), W, H)
    take = " ".join((oslide.takeaway or "").split())
    foot = " ".join((oslide.footnote or "").split())
    if not take and not foot:
        return 0, floor
    try:
        width = int(safe.w * W * 0.85)
        comp, kit = _composer(builder, slide, oslide, outline, manifest, pattern, Bbox(x=int(safe.x * W), y=int(0.8 * H), w=width, h=int(0.12 * H)))
        need = 0
        if take:
            deck_size = comp._takeaway_plan(take, int(safe.w * W))["size"]
            need += comp._takeaway_plan(take, width, sizes=(deck_size,))["h"] + int(kit.vgap * 1.4)
        if foot:
            need += comp.h([comp.P(foot[:1].upper() + foot[1:], comp._footnote_size(), kit.colors.muted)], width) + int(kit.vgap * 0.8)
        return need, floor
    except Exception:  # noqa: BLE001 - the old estimate
        return (int(0.13 * H) if take else 0) + (int(0.06 * H) if foot else 0), floor


def place_notes(builder, slide, oslide: OutlineSlide, outline: DeckOutline, manifest: TemplateManifest, pattern: Pattern) -> Optional[str]:
    """Set the slide's conclusion and footnote under its content. Returns why they did not fit, or None."""
    from verstka.rendering.synth import _content_bottom_limit

    # (a conclusion already set in the sample's own note field is not repeated in a strip)
    take = "" if slide.__dict__.get("_verstka_takeaway_set") else " ".join((oslide.takeaway or "").split())
    foot = " ".join((oslide.footnote or "").split())
    if not take and not foot:
        return None
    W, H = builder.slide_w, builder.slide_h
    ext = _content_extent(slide, pattern, W, H)
    if ext is None:
        return "no content to set the conclusion under"
    left, right, content_bottom = ext
    safe = manifest.tokens.spacing.safe_area
    left = max(left, int(safe.x * W))
    right = min(right, int(safe.x2 * W))
    width = right - left
    if width < 0.35 * W:
        return "the sample's content is too narrow for a conclusion line"
    floor = _content_bottom_limit(slide, int(safe.y2 * H), W, H)
    probe = Bbox(x=left, y=min(content_bottom, floor - 1), w=width, h=max(floor - content_bottom, int(0.05 * H)))
    comp, kit = _composer(builder, slide, oslide, outline, manifest, pattern, probe)
    gap = int(kit.vgap * 1.4)
    room_bottom = floor
    foot_draw = None
    if foot:
        foot = foot[:1].upper() + foot[1:]
        size = comp._footnote_size()
        para = [comp.P(foot, size, kit.colors.muted)]
        fh = comp.h(para, width)
        if floor - fh < content_bottom + int(kit.vgap * 0.8):
            return "no room for the footnote under the sample's content"
        foot_draw = (Bbox(x=left, y=floor - fh, w=width, h=fh), para)
        room_bottom = floor - fh - int(kit.vgap * 0.8)
    plan = None
    if take:
        room = room_bottom - (content_bottom + gap)
        # the deck's one conclusion size — the size a composed slide sets it at across the content width — whatever
        # width the sample leaves: the strip does not jump between 28 and 18 pt from slide to slide
        deck_size = comp._takeaway_plan(take, int(safe.w * W))["size"]
        tries = [lambda: comp._takeaway_plan(take, width, sizes=(deck_size,)), lambda: comp._takeaway_plan(take, width, figure=False, sizes=(deck_size,))]
        for mk in tries:
            p = mk()
            if p["h"] <= room and p.get("lines", 1) <= 3:
                plan = p
                break
        aside = None
        if plan is None:
            # the sample's content runs down to the foot on one side (a chart and its legend beside a short text
            # column): the conclusion takes the largest free stretch at the foot, at least 40 % of the slide wide
            from verstka.rendering.clone_check import free_rect

            fr = free_rect(slide, pattern, manifest, 0.4, 0.08, 0.45, room_bottom)
            if fr is not None:
                fx, fy, fw, fh = fr
                inset = int(0.012 * W)
                p = comp._takeaway_plan(take, fw - 2 * inset, figure=False, sizes=(deck_size,))
                if p["h"] <= fh - inset and p.get("lines", 1) <= 3:
                    plan, aside = p, (fx + inset, fy + fh - p["h"], fw - 2 * inset)
        if plan is None:
            return "no room for the conclusion under the sample's content"
    if plan is not None:
        # at the foot, where a composed slide sets it: the strip stands in one place from slide to slide
        y = room_bottom - plan["h"]
        x = left
        if aside is not None:
            x, y, width = aside[0], min(aside[1], room_bottom - plan["h"]), aside[2]
        # the template's art standing in the strip's band (a 3D render at the foot): the strip takes the widest free
        # stretch beside it, set again for that width
        arts = slide.__dict__.get("_verstka_art_boxes") or []
        free = _free_stretch(arts, x, x + width, y, y + plan["h"], int(0.02 * W))
        if free is not None and (free[0] > x or free[1] < x + width):
            if free[1] - free[0] < 0.4 * W:
                return "the template's art leaves no room for the conclusion"
            x, width = free[0], free[1] - free[0]
            p2 = comp._takeaway_plan(take, width, figure=False)
            if p2["h"] > room_bottom - y:
                return "no room for the conclusion beside the template's art"
            plan = p2
        _cut_rules(slide, Bbox(x=x, y=y, w=width, h=plan["h"]), int(0.02 * H), W, H)
        if plan["strip"]:
            comp.cv.card(Bbox(x=x, y=y, w=width, h=plan["h"]), kit.card, name="Conclusion strip")
        bx = x + plan["pad_x"]
        if plan.get("fig"):
            para_f, fig_w, fig_h, fig_gap = plan["fig"]
            inner = plan["h"] - 2 * plan["pad_y"]
            lsb, _ = comp._figure_optics(para_f, fig_h)
            comp.cv.text(Bbox(x=bx - lsb, y=y + plan["pad_y"] + (inner - fig_h) // 2, w=fig_w + lsb, h=fig_h), [para_f], anchor="ctr", name="Conclusion figure")
            tx = bx + fig_w + fig_gap
            comp.cv.text(Bbox(x=tx, y=y + plan["pad_y"] + (inner - plan["text_h"]) // 2, w=plan["text_w"], h=plan["text_h"]), [plan["para"]], name="Conclusion")
        else:
            from verstka.rendering.compose import _emu

            by = y + plan["pad_y"] + _emu(plan["size"] * 0.12)
            comp.cv.rect(Bbox(x=bx, y=by, w=plan["bar_w"], h=max(plan["text_h"] - _emu(plan["size"] * 0.24), plan["bar_w"] * 3)), plan["colors"].accent, name="Conclusion bar")
            tx = bx + plan["bar_w"] + plan["bar_gap"]
            comp.cv.text(Bbox(x=tx, y=y + plan["pad_y"], w=plan["text_w"], h=plan["text_h"]), [plan["para"]], name="Conclusion")
    if foot_draw is not None:
        comp.cv.text(foot_draw[0], foot_draw[1], name="Footnote")
    return None


SUBTITLE_LOST = "subtitle had no slot"


def lede_height(builder, slide, oslide: OutlineSlide, outline: DeckOutline, manifest: TemplateManifest, pattern: Pattern) -> int:
    """The height of the subtitle's line(s) set as a lede at the body size over 80 % of the content width."""
    sub = " ".join((oslide.subtitle or "").split())
    if not sub:
        return 0
    W, H = builder.slide_w, builder.slide_h
    safe = manifest.tokens.spacing.safe_area
    w_text = int(0.78 * safe.w * W)
    comp, kit = _composer(builder, slide, oslide, outline, manifest, pattern, Bbox(x=int(safe.x * W), y=int(0.2 * H), w=w_text, h=int(0.1 * H)))
    return comp.h([_lede_para(comp, kit, sub)], w_text)


def _lede_para(comp, kit, sub: str):
    """The subtitle as a composed slide sets its intro line: the lead size (body for a long one), muted."""
    size = kit.lead if len(sub) <= 120 else kit.body
    return comp.P(sub[:1].upper() + sub[1:], size, kit.colors.muted if kit.colors.muted != kit.colors.text else kit.colors.text)


def place_lede(builder, slide, oslide: OutlineSlide, outline: DeckOutline, manifest: TemplateManifest, pattern: Pattern, warnings: list[str]) -> None:
    """A content slide's subtitle on a sample without a subtitle box: the line under the heading, as a composed slide
    sets its lede — in the room between the heading's last line and the content (never over it). Set, it takes its
    «subtitle had no slot» off the warnings; without room the warning stays and the gate tries another sample."""
    from verstka.rendering.clone_check import ink_box

    sub = " ".join((oslide.subtitle or "").split())
    if not sub or SUBTITLE_LOST not in warnings:
        return
    W, H = builder.slide_w, builder.slide_h
    title = next((s for s in pattern.slots if s.role == SlotRole.title), None)
    tree = slide._element.cSld.find(q("p:spTree"))
    t_el = None
    if title is not None:
        for el in tree:
            nv = el.find(".//" + q("p:cNvPr"))
            if nv is not None and nv.get("id") == title.shape_id:
                t_el = el
                break
    if t_el is None:
        return
    ib = ink_box(t_el, manifest.tokens.typography.primary_family)
    tb = element_bbox(t_el)
    if ib is None or not tb:
        return
    safe = manifest.tokens.spacing.safe_area
    x = ib.x
    right = int(safe.x2 * W)
    width = max(right - x, 0)
    if width < 0.3 * W:
        return
    y0 = ib.y + ib.h + int(0.015 * H)
    limit = int(safe.y2 * H)
    chrome = set(pattern.chrome_shape_ids)
    for el in tree:
        if el is t_el or etree.QName(el).localname not in _DRAWN:
            continue
        nv = el.find(".//" + q("p:cNvPr"))
        if nv is not None and nv.get("id") in chrome:
            continue
        b = element_bbox(el)
        if not b or b[2] <= 0 or b[3] <= 0 or b[2] * b[3] >= 0.9 * W * H:
            continue
        if etree.QName(el).localname == "sp" and not _paints(el):
            continue
        if b[0] < x + width and b[0] + b[2] > x and b[1] + b[3] > y0:
            if b[1] < y0:
                return  # something stands right under the heading's last line: no room for a line
            limit = min(limit, b[1])
    comp, kit = _composer(builder, slide, oslide, outline, manifest, pattern, Bbox(x=x, y=y0, w=width, h=max(limit - y0, 1)))
    para = _lede_para(comp, kit, sub)
    w_text = min(width, int(0.78 * (int(safe.x2 * W) - int(safe.x * W))))
    hh = comp.h([para], w_text)
    if y0 + hh + int(0.02 * H) > limit:
        return
    comp.cv.text(Bbox(x=x, y=y0, w=w_text, h=hh), [para], name="Subtitle")
    warnings[:] = [w for w in warnings if w != SUBTITLE_LOST]

