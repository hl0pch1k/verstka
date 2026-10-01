"""The gate of a content slide set on a template sample: a clone that loses content, sets type below a readable size
or leaves the sample's own words on the slide is not shown — the renderer tries the next sample, then composes.

A template slide filled with new content is the most faithful way to show the template, and the worst when it
reads badly: a card that lost its text, a figure without its ring, «Безопасность» left in a card. The checks here are
measured on the slide as rendered, so they hold for any template."""

from __future__ import annotations

import re
from typing import Optional

from lxml import etree

from verstka.analysis.xmlns import q
from verstka.schemas.common import EMU_PER_PT
from verstka.schemas.outline import OutlineSlide
from verstka.schemas.common import SlotRole
from verstka.schemas.template import Pattern, TemplateManifest

# warnings of the clone renderer that mean the slide lost a part of its content
LOSS_MARKERS = (
    "items dropped",
    "had no slot",
    "text may overflow",
    "no slot for",
    "pattern has no title slot",
    "native object failed",
    "removed: it cannot show this figure",
    "items merged",
)


# the largest empty rectangle a slide may have gained over its sample (shares of the slide)
HOLE_MIN = 0.15
HOLE_GROWTH = 0.08


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace(" ", " ").replace("⁠", "")).strip().lower()


def _content_strings(oslide: OutlineSlide) -> set[str]:
    c = oslide.content
    out = [oslide.headline, oslide.subtitle or "", oslide.section or "", oslide.takeaway or "", oslide.footnote or ""]
    out += list(c.bullets) + list(c.paragraphs) + [c.quote or "", c.quote_author or ""]
    for it in list(c.items) + list(c.columns):
        out += [it.title, it.text or "", it.number or ""] + list(it.bullets)
    for n in c.numbers:
        out += [n.value, n.label]
    return {_norm(s) for s in out if s}


def _shape_text(el) -> str:
    paras = []
    for p in el.iter(q("a:p")):
        paras.append("".join(t.text or "" for t in p.iter(q("a:t"))))
    return "\n".join(paras)


def readable_floor(manifest: TemplateManifest) -> float:
    """The least size of running text on a slide set on a template sample: the template's body size (a step under
    it at most), never under 2.4 % of the slide height — VK Tech's 9 pt card text on a 5.6-inch slide does not read
    from the back of the room, and a deck of composed slides at 11 pt shows it beside them."""
    hpt = manifest.slide_size.h / EMU_PER_PT
    body = manifest.tokens.typography.size_for("body", 14.0)
    return max(body * 0.85, 0.024 * hpt)


def ink_box(sp, default_family: Optional[str]):
    """Where the text of a box really stands (its lines wrapped at its own size, by its anchor), in EMU; None when it
    has no text or no geometry."""
    from verstka.rendering.deck import element_bbox
    from verstka.rendering.fonts import wrap_lines
    from verstka.schemas.common import Bbox

    b = element_bbox(sp)
    if not b or b[2] <= 0 or b[3] <= 0:
        return None
    body = sp.find(q("p:txBody"))
    if body is None:
        return None
    bp = body.find(q("a:bodyPr"))

    def ins(name: str, default: int) -> int:
        try:
            return int(bp.get(name)) if bp is not None and bp.get(name) is not None else default
        except ValueError:
            return default

    l, tp, r, bt = ins("lIns", 91440), ins("tIns", 45720), ins("rIns", 91440), ins("bIns", 45720)
    width = max((b[2] - l - r) / EMU_PER_PT, 1.0)
    height = 0.0
    widest = 0.0
    for p in body.findall(q("a:p")):
        text = "".join(x.text or "" for x in p.iter(q("a:t")))
        rpr = next((x for x in p.iter(q("a:rPr")) if x.get("sz")), None)
        size = int(rpr.get("sz")) / 100 if rpr is not None else 12.0
        lat = rpr.find(q("a:latin")) if rpr is not None else None
        fam = lat.get("typeface") if lat is not None and lat.get("typeface") else default_family
        pct = p.find(q("a:pPr") + "/" + q("a:lnSpc") + "/" + q("a:spcPct"))
        ls = 1.2 * (int(pct.get("val")) / 100000 if pct is not None and pct.get("val") else 1.0)
        lines = wrap_lines(text, fam, size, bool(rpr is not None and rpr.get("b") == "1"), width) if text.strip() else [""]
        height += max(len(lines), 1) * size * ls
        if text.strip():
            from verstka.rendering.fonts import text_width_pt

            widest = max(widest, max(text_width_pt(x, fam, size) for x in lines))
    if widest <= 0:
        return None
    h = int(height * EMU_PER_PT)
    anchor = (bp.get("anchor") if bp is not None else None) or "t"
    inner_h = b[3] - tp - bt
    y = b[1] + tp + (max(inner_h - h, 0) // 2 if anchor == "ctr" else (max(inner_h - h, 0) if anchor == "b" else 0))
    return Bbox(x=b[0] + l, y=y, w=min(int(widest * EMU_PER_PT), b[2] - l - r), h=min(h, max(b[3], h)))


_GRID_C, _GRID_R = 48, 27


def _covered(slide, pattern: Pattern, manifest: TemplateManifest):
    """The cells of a 48 × 27 grid over the slide that its content covers: painted shapes, pictures, charts and
    tables by their boxes, text by the lines it really takes (the box's width, the height its lines fill). Hairlines
    and full-slide grounds cover nothing. Returns (grid, the content area as cell bounds)."""
    import numpy as np

    from verstka.rendering.clone_notes import _paints
    from verstka.rendering.deck import element_bbox

    W, H = manifest.slide_size.w, manifest.slide_size.h
    grid = np.zeros((_GRID_R, _GRID_C), dtype=bool)
    fam = manifest.tokens.typography.primary_family
    tree = slide._element.cSld.find(q("p:spTree"))

    def mark(x: float, y: float, w: float, h: float) -> None:
        if w <= 0 or h <= 0:
            return
        c0, c1 = int(max(x, 0) / W * _GRID_C), int(min(x + w, W) / W * _GRID_C - 1e-9)
        r0, r1 = int(max(y, 0) / H * _GRID_R), int(min(y + h, H) / H * _GRID_R - 1e-9)
        if c1 >= c0 and r1 >= r0:
            grid[max(r0, 0) : min(r1, _GRID_R - 1) + 1, max(c0, 0) : min(c1, _GRID_C - 1) + 1] = True

    for el in tree:
        tag = etree.QName(el).localname
        if tag not in ("sp", "pic", "grpSp", "graphicFrame", "cxnSp"):
            continue
        b = element_bbox(el)
        if not b or b[2] <= 0 or b[3] <= 0 or b[2] * b[3] >= 0.9 * W * H:
            continue
        if tag == "cxnSp" or min(b[2] / W, b[3] / H) < 0.01:
            continue  # a rule or a connector divides the room, it does not fill it
        if tag == "sp" and not _paints(el):
            continue
        if tag == "sp" and _shape_text(el).strip() and not _fills_box(el):
            ib = ink_box(el, fam)
            if ib is not None:
                mark(b[0], ib.y, b[2], ib.h)
            continue
        mark(*b)
    safe = manifest.tokens.spacing.safe_area
    top = max((s.bbox.y2 for s in pattern.slots if s.role == SlotRole.title), default=safe.y)
    area = (int(safe.x * _GRID_C), int(min(top + 0.02, 0.5) * _GRID_R), int(safe.x2 * _GRID_C), int(safe.y2 * _GRID_R))
    return grid, area


def _fills_box(el) -> bool:
    """A text shape whose own fill or outline draws its box (a card, a pill): it covers the box, not only its lines."""
    spPr = el.find(q("p:spPr"))
    if spPr is None:
        return False
    if spPr.find(q("a:noFill")) is None and any(spPr.find(q(x)) is not None for x in ("a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill")):
        return True
    ln = spPr.find(q("a:ln"))
    return ln is not None and ln.find(q("a:noFill")) is None and any(ln.find(q(x)) is not None for x in ("a:solidFill", "a:gradFill"))


def largest_hole(grid, area) -> float:
    """The largest empty rectangle of the content area, as a share of the slide."""
    c0, r0, c1, r1 = area
    heights = [0] * _GRID_C
    best = 0
    for r in range(max(r0, 0), min(r1, _GRID_R)):
        for c in range(_GRID_C):
            heights[c] = heights[c] + 1 if (c0 <= c < c1 and not grid[r, c]) else 0
        stack: list[int] = []
        for c in range(_GRID_C + 1):
            h = heights[c] if c < _GRID_C else 0
            while stack and heights[stack[-1]] >= h:
                top = stack.pop()
                width = c if not stack else c - stack[-1] - 1
                best = max(best, heights[top] * width)
            stack.append(c)
    return best / float(_GRID_C * _GRID_R)


def free_rect(slide, pattern: Pattern, manifest: TemplateManifest, min_w: float, min_h: float, y_from: float, floor_emu: int):
    """The largest empty rectangle of the slide below `y_from` (a share of the height) and above `floor_emu`, at
    least `min_w` × `min_h` (shares of the slide): (x, y, w, h) in EMU, or None. Where a conclusion can stand when
    the sample's content runs down to the foot on one side (a chart and its legend beside a short text column)."""
    import numpy as np  # noqa: F401

    W, H = manifest.slide_size.w, manifest.slide_size.h
    grid, area = _covered(slide, pattern, manifest)
    c0, _, c1, _ = area
    r0 = int(y_from * _GRID_R + 0.999)
    r1 = min(int(floor_emu / H * _GRID_R), _GRID_R)
    best = None
    heights = [0] * _GRID_C
    for r in range(max(r0, 0), r1):
        for c in range(_GRID_C):
            heights[c] = heights[c] + 1 if (c0 <= c < c1 and not grid[r, c]) else 0
        stack: list[int] = []
        for c in range(_GRID_C + 1):
            h = heights[c] if c < _GRID_C else 0
            while stack and heights[stack[-1]] >= h:
                top = stack.pop()
                left = stack[-1] + 1 if stack else 0
                width = c - left
                hh = heights[top]
                if width / _GRID_C >= min_w and hh / _GRID_R >= min_h and (best is None or width * hh > best[2] * best[3]):
                    best = (left, r - hh + 1, width, hh)
            stack.append(c)
    if best is None:
        return None
    cx, ry, cw, rh = best
    return (int(cx / _GRID_C * W), int(ry / _GRID_R * H), int(cw / _GRID_C * W), int(rh / _GRID_R * H))


def sample_hole(slide, pattern: Pattern, manifest: TemplateManifest) -> Optional[float]:
    """The largest empty rectangle of the sample as the template draws it (measured on the fresh copy)."""
    try:
        grid, area = _covered(slide, pattern, manifest)
        return largest_hole(grid, area)
    except Exception:  # noqa: BLE001
        return None


def content_trouble(slide, oslide: OutlineSlide, pattern: Pattern, manifest: TemplateManifest, warnings: list[str]) -> Optional[str]:
    """Why a content slide set on `pattern` must not be shown, or None."""
    for w in warnings:
        for m in LOSS_MARKERS:
            if m in w:
                return w
    c = oslide.content
    if c.chart2 is not None or (c.formula or "").strip() or c.photo_slot:
        return "a second chart, a formula or a photo place: the composer sets them"
    if c.chart is not None and c.table is not None:
        return "a chart and a table on one slide"
    H = manifest.slide_size.h
    hpt = H / EMU_PER_PT
    typo = manifest.tokens.typography
    body = typo.size_for("body", 14.0)
    small = typo.size_for("small", body * 0.8)
    run_floor = readable_floor(manifest)
    label_floor = max(small * 0.9, 0.016 * hpt)
    samples = {_norm(s.sample_text) for s in pattern.slots if s.sample_text and len(_norm(s.sample_text)) >= 3}
    ours = _content_strings(oslide)
    tree = slide._element.cSld.find(q("p:spTree"))
    chrome = set(pattern.chrome_shape_ids)
    # text written over the template's art (a 3D render in a card): the art stays, so the text must stand clear of it
    arts = slide.__dict__.get("_verstka_art_boxes") or []
    designed = slide.__dict__.get("_verstka_designed") or {}
    if arts:
        fam = manifest.tokens.typography.primary_family
        for sp in tree.iter(q("p:sp")):
            nv = sp.find(".//" + q("p:cNvPr"))
            sid = nv.get("id") if nv is not None else None
            if sid in chrome:
                continue
            ib = ink_box(sp, fam)
            if ib is None or ib.area <= 0:
                continue
            own = designed.get(sid)
            own_ink = (slide.__dict__.get("_verstka_designed_ink") or {}).get(sid)
            for a in arts:
                ov = ib.intersection(a)
                if ov <= 0.03 * ib.area:
                    continue
                if own_ink is not None:
                    # the sample sets its own words over the art: ours may cover as much of it as they did, a little more
                    if ov <= 1.25 * own_ink.intersection(a) + 0.03 * ib.area:
                        continue
                elif own is not None and own.intersection(a) > 0.1 * max(own.area, 1):
                    continue  # the sample sets this text over the art itself
                return f"text «{_shape_text(sp).strip()[:24]}» runs over the template's art"

    # a heading squeezed far below the deck's heading size (a long headline in a sample's short title bar): the deck's
    # headings would jump from slide to slide
    heads = [s for s in pattern.slots if s.role == SlotRole.title]
    if heads and (oslide.headline or "").strip():
        h1 = slide.__dict__.get("_verstka_head_size") or typo.size_for("h1", 0.0)
        ref = min(x for x in (heads[0].style.size_pt or 0.0, h1) if x > 0) if (heads[0].style.size_pt or h1) else 0.0
        el = next((x for x in tree.iter(q("p:sp")) if (x.find(".//" + q("p:cNvPr")) is not None and x.find(".//" + q("p:cNvPr")).get("id") == heads[0].shape_id)), None)
        sizes = [int(r.get("sz")) / 100 for r in el.iter(q("a:rPr")) if r.get("sz")] if el is not None else []
        if ref and sizes and min(sizes) < 0.75 * ref - 0.05:
            return f"the heading had to shrink to {min(sizes):g} pt (the deck sets {ref:g} pt)"
    # figures squeezed far below the sample's own (VK Tech p42: two display figures, three of ours set at a label's
    # size in narrowed cells): the sample's point — the big number — is lost
    nums = {s.shape_id: (s.style.size_pt or 0.0) for s in pattern.slots if s.role == SlotRole.number and (s.style.size_pt or 0.0) >= 20}
    if nums:
        origin = slide.__dict__.get("_verstka_origin") or {}
        for sp in tree.iter(q("p:sp")):
            nv = sp.find(".//" + q("p:cNvPr"))
            sid = nv.get("id") if nv is not None else None
            own = nums.get(origin.get(sid, sid)) if sid else None
            if not own or not _shape_text(sp).strip():
                continue
            sizes = [int(r.get("sz")) / 100 for r in sp.iter(q("a:rPr")) if r.get("sz")]
            if sizes and max(sizes) < 0.5 * own:
                return f"figure «{_shape_text(sp).strip()[:12]}» set at {max(sizes):g} pt where the sample sets {own:g} pt"
    # the heading's lines run into the content under them (a headline of two lines over a sample made for one)
    if heads:
        t_el = next((x for x in tree.iter(q("p:sp")) if (x.find(".//" + q("p:cNvPr")) is not None and x.find(".//" + q("p:cNvPr")).get("id") == heads[0].shape_id)), None)
        tib = ink_box(t_el, manifest.tokens.typography.primary_family) if t_el is not None else None
        if tib is not None and tib.area > 0:
            from verstka.rendering.deck import element_bbox
            from verstka.schemas.common import Bbox

            for el in tree:
                if el is t_el or etree.QName(el).localname not in ("sp", "pic", "graphicFrame", "grpSp"):
                    continue
                nv = el.find(".//" + q("p:cNvPr"))
                if nv is not None and nv.get("id") in chrome:
                    continue
                b = element_bbox(el)
                if not b or b[2] <= 0 or b[3] <= 0 or b[2] * b[3] >= 0.5 * manifest.slide_size.w * H:
                    continue
                ob = Bbox(x=b[0], y=b[1], w=b[2], h=b[3])
                if ob.contains_point(tib.x + tib.w / 2, tib.y + tib.h / 2):
                    continue  # the heading's own pill or band
                if etree.QName(el).localname == "pic":
                    try:
                        from verstka.rendering.layers import opaque_box

                        ob = opaque_box(slide.part, el, ob)  # a render's transparent margin is no obstacle
                    except Exception:  # noqa: BLE001
                        pass
                    if ob.w <= 0 or ob.h <= 0:
                        continue
                if etree.QName(el).localname == "sp":
                    if _shape_text(el).strip():
                        ob = ink_box(el, manifest.tokens.typography.primary_family) or ob
                    else:
                        from verstka.rendering.clone_notes import _paints

                        if not _paints(el):
                            continue
                if ob.y > tib.y and tib.intersection(ob) > 0.04 * tib.area:
                    return f"the heading runs into «{_shape_text(el).strip()[:20] or etree.QName(el).localname}» under it"
    # text running out of the card it starts in (a third line of a card's text under the card's foot)
    native = slide.__dict__.get("_verstka_native") or set()
    cards = []
    from verstka.rendering.clone_notes import _paints as _paints_c
    from verstka.rendering.deck import element_bbox as _ebox
    from verstka.schemas.common import Bbox as _Bbox

    for el in tree:
        if etree.QName(el).localname != "sp" or _shape_text(el).strip() or not _paints_c(el):
            continue
        b = _ebox(el)
        if b and b[2] > 0 and b[3] > 0 and b[2] * b[3] < 0.5 * manifest.slide_size.w * H:
            cards.append(_Bbox(x=b[0], y=b[1], w=b[2], h=b[3]))
    if cards:
        fam_c = manifest.tokens.typography.primary_family
        for sp in tree.iter(q("p:sp")):
            nv = sp.find(".//" + q("p:cNvPr"))
            if nv is not None and (nv.get("id") in chrome or nv.get("id") in native):
                continue
            if not _shape_text(sp).strip():
                continue
            ib = ink_box(sp, fam_c)
            if ib is None:
                continue
            home = [c for c in cards if c.contains_point(ib.x + min(ib.w, c.w) / 2, ib.y + 1) and c.area >= 1.3 * ib.w * min(ib.h, c.h)]
            if home:
                card = min(home, key=lambda c: c.area)
                if ib.y + ib.h > card.y2 + 0.01 * H:
                    return f"text «{_shape_text(sp).strip()[:24]}» runs out of its card"
    # a hole where the sample had its content: cells, a band, a card or a picture taken off and nothing in their
    # place (WorkSpace p15 without its note band, LCT p20 without its big card) — the composer sets such content better
    hole0 = slide.__dict__.get("_verstka_hole0")
    if hole0 is not None:
        try:
            grid, area = _covered(slide, pattern, manifest)
            hole = largest_hole(grid, area)
            slide.__dict__["_verstka_hole"] = hole
            if hole >= HOLE_MIN and hole - hole0 >= HOLE_GROWTH:
                return f"a hole of {hole:.0%} of the slide where the sample had {hole0:.0%} free"
        except Exception:  # noqa: BLE001
            pass
    # the design system's table or chart squeezed into a sample's small area: its type below the deck's own data size
    if native:
        data_floor = 0.85 * min(manifest.components.table_style.font_size_pt, manifest.components.chart_style.font_size_pt)
        for el in tree:
            nv = el.find(".//" + q("p:cNvPr"))
            if nv is None or nv.get("id") not in native or etree.QName(el).localname != "graphicFrame":
                continue
            sizes = [int(r.get("sz")) / 100 for r in el.iter(q("a:rPr")) if r.get("sz")]
            if sizes and min(sizes) < data_floor - 0.05:
                return f"the table or chart set at {min(sizes):g} pt, below the deck's {data_floor / 0.85:g} pt for data"
    for sp in tree.iter(q("p:sp")):
        nv = sp.find(".//" + q("p:cNvPr"))
        if nv is not None and (nv.get("id") in chrome or nv.get("id") in native):
            continue
        text = _shape_text(sp)
        if not text.strip():
            continue
        n = _norm(text)
        if n in samples and n not in ours and not any(n in o for o in ours):
            return f"sample text «{text.strip()[:30]}» left on the slide"
        from verstka.rendering.deck import element_bbox
        from verstka.rendering.fonts import text_width_pt

        b_sp = element_bbox(sp)
        bp_sp = sp.find(q("p:txBody") + "/" + q("a:bodyPr"))

        def _ins(name: str, default: int) -> int:
            try:
                return int(bp_sp.get(name)) if bp_sp is not None and bp_sp.get(name) is not None else default
            except ValueError:
                return default

        usable = (b_sp[2] - _ins("lIns", 91440) - _ins("rIns", 91440)) / EMU_PER_PT if b_sp else 0.0
        wrap_on = bp_sp is None or bp_sp.get("wrap") != "none"
        for p in sp.iter(q("a:p")):
            ptxt = "".join(t.text or "" for t in p.iter(q("a:t")))
            if not ptxt.strip():
                continue
            sizes = [int(r.get("sz")) / 100 for r in p.iter(q("a:rPr")) if r.get("sz")]
            if not sizes:
                continue
            if usable > 0 and wrap_on and nv is not None and nv.get("id") not in native:
                # a word (or words bound by no-break spaces) wider than its box is broken across lines by the renderer
                rpr = next((r for r in p.iter(q("a:rPr")) if r.get("sz")), None)
                lat = rpr.find(q("a:latin")) if rpr is not None else None
                fam_p = lat.get("typeface") if lat is not None and lat.get("typeface") else typo.primary_family
                bold_p = bool(rpr is not None and rpr.get("b") == "1")
                for chunk in ptxt.split():
                    if len(chunk) >= 4 and text_width_pt(chunk, fam_p, max(sizes), bold_p) > usable * 1.01:
                        return f"«{chunk.replace(chr(160), ' ')[:24]}» is wider than its box and breaks mid-word"
            size = min(sizes)
            floor = run_floor if len(ptxt.strip()) >= 25 else label_floor
            if size < floor - 0.05:
                return f"text «{ptxt.strip()[:24]}» set at {size:g} pt, below {floor:.1f} pt"
    return None
