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


def turned_box(el, box: Bbox) -> Bbox:
    """`box` — a part of the shape `el` (its letters), in slide EMU as if the shape were not turned — as it stands on
    the slide: the box around its corners turned with the shape about the shape's centre. `box` itself when the shape
    is not turned (or has no geometry)."""
    import math

    tag = etree.QName(el).localname
    xfrm = el.find(q("p:grpSpPr") + "/" + q("a:xfrm")) if tag == "grpSp" else (el.find(q("p:spPr") + "/" + q("a:xfrm")) if el.find(q("p:spPr")) is not None else None)
    eb = element_bbox(el)
    try:
        rot = int(xfrm.get("rot") or 0) / 60000.0 if xfrm is not None else 0.0
    except ValueError:
        rot = 0.0
    a = ((rot + 180.0) % 360.0) - 180.0
    if abs(a) < 0.5 or not eb:
        return box
    t = math.radians(a)
    cx, cy = eb[0] + eb[2] / 2.0, eb[1] + eb[3] / 2.0
    pts = [(cx + (px - cx) * math.cos(t) - (py - cy) * math.sin(t), cy + (px - cx) * math.sin(t) + (py - cy) * math.cos(t)) for px in (box.x, box.x2) for py in (box.y, box.y2)]
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    return Bbox(x=int(x0), y=int(y0), w=max(int(x1 - x0), 1), h=max(int(y1 - y0), 1))


def _content_extent(slide, pattern: Pattern, W: int, H: int) -> Optional[tuple[int, int, int]]:
    """(left, right, bottom) of what the slide shows, its chrome, full-slide grounds and the marks at its foot aside."""
    chrome = set(pattern.chrome_shape_ids)
    titles = {s.shape_id for s in pattern.slots if s.role == SlotRole.title and (s.style.align or "") == "ctr"}
    tree = slide._element.cSld.find(q("p:spTree"))
    left, right, bottom = None, None, None
    h_left = h_right = None  # a centred heading's box: the content's column only when nothing else sets it
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
        bottom = b[1] + b[3] if bottom is None else max(bottom, b[1] + b[3])
        if nv is not None and nv.get("id") in titles:
            # (a centred heading's box widened about its centre spans the band: the conclusion keeps to the content's
            # column under it, not to the heading's box)
            h_left, h_right = b[0], b[0] + b[2]
            continue
        left = b[0] if left is None else min(left, b[0])
        right = b[0] + b[2] if right is None else max(right, b[0] + b[2])
    if left is None:
        if h_left is None:
            return None
        left, right = h_left, h_right
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


def _room_under_heading(slide, pattern: Pattern, manifest: TemplateManifest, W: int, H: int) -> Optional[tuple[int, int, int, int]]:
    """(x, top, width, bottom) of the band between the heading's last line and the first thing drawn under it in
    its column, or None (no heading, something right under it, a band narrower than 40 % of the slide)."""
    from verstka.rendering.clone_check import ink_box

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
        return None
    ib = ink_box(t_el, manifest.tokens.typography.primary_family)
    if ib is None:
        return None
    # a heading turned with its band: its letters as they stand on the slide — the line under the unturned letters ran
    # over the low end of the tilted heading
    ib = turned_box(t_el, ib)
    safe = manifest.tokens.spacing.safe_area
    x = ib.x
    width = int(safe.x2 * W) - x
    if width < 0.4 * W:
        return None
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
        if etree.QName(el).localname == "sp" and not _paints(el) and not "".join(t.text or "" for t in el.iter(q("a:t"))).strip():
            continue
        if b[0] < x + width and b[0] + b[2] > x and b[1] + b[3] > y0:
            if b[1] < y0:
                return None  # something stands right under the heading's last line
            limit = min(limit, b[1])
    return x, y0, width, limit


def _conclusion_under_heading(builder, slide, oslide: OutlineSlide, outline: DeckOutline, manifest: TemplateManifest, pattern: Pattern, take: str, deck_size: float) -> bool:
    """The conclusion of a sample whose content runs down to its foot (VK Tech p28: three cards with their 3D renders
    to the bottom of the area) stands as the line under the heading — the accent bar and the line at the deck's
    conclusion size, a step smaller at the least — when the band between the heading and the content holds it."""
    W, H = builder.slide_w, builder.slide_h
    band = _room_under_heading(slide, pattern, manifest, W, H)
    if band is None:
        return False
    x, y0, width, limit = band
    comp, kit = _composer(builder, slide, oslide, outline, manifest, pattern, Bbox(x=x, y=y0, w=width, h=max(limit - y0, 1)))
    for size in dict.fromkeys((deck_size, kit.body, kit.small)):
        if size < kit.small - 0.05:
            continue
        plan = comp._takeaway_plan(take, min(width, int(0.9 * width)), figure=False, sizes=(size,))
        if plan.get("lines", 1) > 2 or y0 + plan["h"] + int(0.015 * H) > limit:
            continue
        if plan["strip"] and limit - y0 - plan["h"] < int(0.03 * H):
            continue  # a strip squeezed against the cards reads as a fourth card: the bar alone, a step smaller
        _draw_conclusion(comp, plan, x, y0)
        return True
    return False


def _draw_conclusion(comp, plan: dict, x: int, y: int) -> None:
    """The conclusion as a composed slide draws it: on its strip, or as the accent bar and the line beside it."""
    from verstka.rendering.compose import _emu

    if plan["strip"]:
        comp.cv.card(Bbox(x=x, y=y, w=plan["text_w"] + 2 * plan["pad_x"] + plan["bar_w"] + plan["bar_gap"], h=plan["h"]), comp.kit.card, name="Conclusion strip")
    bx = x + plan["pad_x"]
    by = y + plan["pad_y"] + _emu(plan["size"] * 0.12)
    comp.cv.rect(Bbox(x=bx, y=by, w=plan["bar_w"], h=max(plan["text_h"] - _emu(plan["size"] * 0.24), plan["bar_w"] * 3)), plan["colors"].accent, name="Conclusion bar")
    tx = bx + plan["bar_w"] + plan["bar_gap"]
    comp.cv.text(Bbox(x=tx, y=y + plan["pad_y"], w=plan["text_w"], h=plan["text_h"]), [plan["para"]], name="Conclusion")


def _chart_down_to(slide, content_bottom: int, to_y: int, left: int, right: int, H: int) -> None:
    """The slide's chart grows down to the conclusion set at the foot (`to_y`): the room the renderer kept for the
    conclusion is measured for its widest form, the strip drawn is often a line or two shorter — the band between the
    chart and the strip stayed empty (VK Tech, data slides: 53 pt under a 150 pt chart). Only a chart whose foot is the
    content's foot and that stands over the strip; a table keeps its rows' height."""
    from verstka.rendering.deck import set_element_pos

    if to_y - content_bottom < int(0.03 * H):
        return
    tree = slide._element.cSld.find(q("p:spTree"))
    for el in tree:
        if etree.QName(el).localname != "graphicFrame" or not any(True for _ in el.iter("{http://schemas.openxmlformats.org/drawingml/2006/chart}chart")):
            continue
        b = element_bbox(el)
        if not b or abs(b[1] + b[3] - content_bottom) > int(0.01 * H) or min(b[0] + b[2], right) - max(b[0], left) <= 0:
            continue
        # (never more than half again its height: a chart is not stretched into a tower)
        set_element_pos(el, h=min(to_y - b[1], int(b[3] * 1.5)))


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
        fx, fw = left, width
        try:
            from verstka.rendering.layers import clear_of_rules

            # a rule of the layout through the foot (Классика: the hairline down the middle of the slide) — the small
            # print keeps to one side of it, on two lines if it must
            cl = clear_of_rules(slide, Bbox(x=left, y=floor - fh, w=width, h=fh))
            if cl.w < width and cl.w >= 0.3 * W:
                fx, fw = cl.x, cl.w
                fh = comp.h(para, fw)
        except Exception:  # noqa: BLE001 - the foot as measured
            pass
        if floor - fh < content_bottom + int(kit.vgap * 0.8):
            return "no room for the footnote under the sample's content"
        foot_draw = (Bbox(x=fx, y=floor - fh, w=fw, h=fh), para)
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
                # the strip starts on a column of the slide's content (the left edge of a text standing over it), not
                # wherever the free stretch happens to begin (VK Education: a box starting between two columns)
                tree0 = slide._element.cSld.find(q("p:spTree"))
                lefts = sorted({b[0] for b in (element_bbox(x) for x in tree0 if etree.QName(x).localname == "sp" and "".join(t.text or "" for t in x.iter(q("a:t"))).strip()) if b and b[1] + b[3] <= fy + int(0.02 * H) and fx <= b[0] < fx + fw // 2})
                snapped = bool(lefts) and fx + fw - lefts[0] >= int(0.4 * W)
                if snapped:
                    fw, fx = fx + fw - lefts[0], lefts[0]
                inset = int(0.012 * W)
                if snapped:
                    fx -= inset  # (the strip's own edge on the column: the inset below is taken back)
                    fw += inset
                p = comp._takeaway_plan(take, fw - 2 * inset, figure=False, sizes=(deck_size,))
                if p["h"] <= fh - inset and p.get("lines", 1) <= 3:
                    plan, aside = p, (fx + inset, fy + fh - p["h"], fw - 2 * inset)
        if plan is None:
            if _conclusion_under_heading(builder, slide, oslide, outline, manifest, pattern, take, deck_size):
                take = ""
            else:
                return "no room for the conclusion under the sample's content"
    if plan is not None:
        # at the foot, where a composed slide sets it: the strip stands in one place from slide to slide
        y = room_bottom - plan["h"]
        x = left
        if aside is not None:
            x, y, width = aside[0], min(aside[1], room_bottom - plan["h"]), aside[2]
        if aside is None:
            _chart_down_to(slide, content_bottom, y - gap, left, right, H)
        # the template's art standing in the strip's band (a 3D render at the foot): the strip takes the widest free
        # stretch beside it, set again for that width
        arts = slide.__dict__.get("_verstka_art_boxes") or []
        free = _free_stretch(arts, x, x + width, y, y + plan["h"], int(0.02 * W))
        if free is not None and (free[0] > x or free[1] < x + width):
            p2 = None
            if free[1] - free[0] >= 0.4 * W:
                x, width = free[0], free[1] - free[0]
                # narrower, the strip may take another line: it rises into the room under the content, at the deck's size
                p2 = comp._takeaway_plan(take, width, figure=False, sizes=(deck_size,))
                if p2.get("lines", 1) > 3 or p2["h"] > room_bottom - (content_bottom + gap):
                    p2 = None
            if p2 is None:
                # the art at the foot leaves the strip no room: the line under the heading, when that band holds it
                if not _conclusion_under_heading(builder, slide, oslide, outline, manifest, pattern, take, deck_size):
                    return "the template's art leaves no room for the conclusion"
                if foot_draw is not None:
                    _cut_rules(slide, foot_draw[0], int(0.02 * H), W, H)
                    comp.cv.text(foot_draw[0], foot_draw[1], name="Footnote")
                return None
            y = room_bottom - p2["h"] if aside is None else min(y, room_bottom - p2["h"])
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
    if foot_draw is not None and plan is None and not take:
        _chart_down_to(slide, content_bottom, room_bottom - gap, left, right, H)
    if foot_draw is not None:
        # (a vertical rule of the sample's grid running down to the foot ends above the small print, as above the strip)
        _cut_rules(slide, foot_draw[0], int(0.02 * H), W, H)
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

