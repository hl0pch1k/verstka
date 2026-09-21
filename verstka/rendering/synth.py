"""Synth renderer: compose a slide from template tokens and components when no sample pattern fits."""

from __future__ import annotations

import math
from collections import Counter
from typing import Optional

from lxml import etree
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.slide import Slide
from pptx.util import Emu, Pt

from verstka.analysis.xmlns import q
from verstka.ingest.workspace import TemplateWorkspace
from verstka.rendering.assets_pick import pick_asset
from verstka.rendering.charts import add_chart
from verstka.rendering.deck import DeckBuilder
from verstka.rendering.fit import fit_size
from verstka.rendering.images import insert_picture
from verstka.rendering.tables import add_table
from verstka.rendering.textfill import ParagraphSpec, fill_text
from verstka.schemas.common import Bbox, Family, PatternKind, SlotRole, contrast_ratio
from verstka.schemas.layout import LayoutSlide
from verstka.schemas.outline import DeckOutline, OutlineSlide, SlideItem
from verstka.schemas.template import Pattern, TemplateManifest


class _Palette:
    def __init__(self, manifest: TemplateManifest, family: Family) -> None:
        t = manifest.tokens
        self.family = family
        self.bg = t.color_for("background.dark" if family == Family.dark else "background.light") or ("000000" if family == Family.dark else "FFFFFF")
        text = t.color_for("text.primary") or ("FFFFFF" if family == Family.dark else "000000")
        if contrast_ratio(text, self.bg) < 3.0:
            text = "FFFFFF" if family == Family.dark else "000000"
        self.text = text
        sec = t.color_for("text.secondary")
        self.text2 = sec if sec and contrast_ratio(sec, self.bg) >= 3.0 else self.text
        self.accent = t.accents()[0] if t.accents() else "0077FF"
        surf = t.color_for("surface")
        self.surface = surf if surf and 1.02 < contrast_ratio(surf, self.bg) < 2.5 else None
        card = manifest.components.card
        self.card_fill = (card.fill_hex if card and card.fill_hex and 1.0 < contrast_ratio(card.fill_hex, self.bg) < 3.0 else self.surface)
        self.card_line = card.line_hex if card else None
        self.radius = (card.radius if card and card.radius is not None else (t.shapes.typical_radius or 0.08))


def _family_for(oslide: OutlineSlide, manifest: TemplateManifest) -> Family:
    fams = Counter(p.family for p in manifest.patterns if p.kind == oslide.kind)
    if fams:
        return fams.most_common(1)[0][0]
    fams = Counter(p.family for p in manifest.patterns)
    return fams.most_common(1)[0][0] if fams else Family.light


def _layout_for(builder: DeckBuilder, manifest: TemplateManifest, family: Family, kind: PatternKind):
    """Layout used by the most sample slides of this family (prefer same kind, then content kinds)."""
    prefs = [p for p in manifest.patterns if p.family == family and p.kind == kind and p.layout_part]
    if not prefs:
        prefs = [p for p in manifest.patterns if p.family == family and p.layout_part and p.kind in (PatternKind.bullets, PatternKind.cards, PatternKind.freeform, PatternKind.two_column, PatternKind.stat_row)]
    if not prefs:
        prefs = [p for p in manifest.patterns if p.family == family and p.layout_part]
    counts = Counter(p.layout_part for p in prefs)
    by_partname = {str(l.part.partname).lstrip("/"): l for l in builder.prs.slide_layouts}
    for part, _ in counts.most_common():
        if part in by_partname:
            return by_partname[part]
    return builder.prs.slide_layouts[-1]


def _title_style(manifest: TemplateManifest, family: Family, pal: _Palette) -> tuple[float, str, bool, Optional[str]]:
    slots = [s for p in manifest.patterns if p.family == family for s in p.slots if s.role == SlotRole.title and s.style.size_pt]
    size = manifest.tokens.typography.size_for("h1", 28.0)
    color = pal.text
    bold = False
    font = manifest.tokens.typography.primary_family
    if slots:
        sizes = Counter(round(s.style.size_pt or size) for s in slots)
        size = float(sizes.most_common(1)[0][0])
        colors = Counter(s.style.color_hex for s in slots if s.style.color_hex)
        if colors:
            cand = colors.most_common(1)[0][0]
            if contrast_ratio(cand, pal.bg) >= 3.0:
                color = cand
        bold = sum(1 for s in slots if s.style.bold) > len(slots) / 2
        fonts = Counter(s.style.font_family for s in slots if s.style.font_family)
        if fonts:
            font = fonts.most_common(1)[0][0]
    return size, color, bold, font


def _textbox(slide: Slide, box: Bbox, paragraphs: list[ParagraphSpec], *, size: float, color: str, font: Optional[str], bold: bool = False, align: str = "l", anchor: str = "t", scale: Optional[list[float]] = None, line_spacing: float = 1.2, fit: bool = True):
    tb = slide.shapes.add_textbox(Emu(box.x), Emu(box.y), Emu(box.w), Emu(box.h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Emu(45720)
    tf.margin_top = tf.margin_bottom = Emu(22860)
    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "ctr": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}[anchor]
    target = size
    if fit:
        res = fit_size([p.text for p in paragraphs], box, font, size, bold, scale or [], insets_emu=(45720, 22860, 45720, 22860), line_spacing=line_spacing, min_ratio=0.55)
        target = res.size_pt
    p0 = tf.paragraphs[0]
    p0.alignment = {"l": PP_ALIGN.LEFT, "ctr": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}[align]
    r = p0.add_run()
    r.text = ""
    r.font.size = Pt(target)
    r.font.bold = bold
    r.font.color.rgb = RGBColor.from_string(color)
    if font:
        r.font.name = font
    specs = [ParagraphSpec(p.text, bullet=p.bullet, level=p.level, bold=p.bold if p.bold is not None else None, size_pt=p.size_pt, color_hex=p.color_hex) for p in paragraphs]
    fill_text(tb._element, specs, size_pt=target)
    if any(p.bullet for p in paragraphs):
        for pPr in tb._element.iter(q("a:pPr")):
            if pPr.find(q("a:buChar")) is not None:
                pPr.set("marL", "285750")
                pPr.set("indent", "-285750")
    for p in tb.text_frame.paragraphs:
        p.alignment = p0.alignment
        p.space_after = Pt(max(target * 0.35, 3))
    return tb


def _rect(slide: Slide, box: Bbox, fill: Optional[str], line: Optional[str], radius: float):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius > 0 else MSO_SHAPE.RECTANGLE, Emu(box.x), Emu(box.y), Emu(box.w), Emu(box.h))
    if radius > 0:
        shape.adjustments[0] = min(max(radius, 0.0), 0.5)
    if fill:
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string(fill)
    else:
        shape.fill.background()
    if line:
        shape.line.color.rgb = RGBColor.from_string(line)
        shape.line.width = Pt(0.75)
    else:
        shape.line.fill.background()
    shape.shadow.inherit = False
    shape.text_frame.text = ""
    return shape


def _circle(slide: Slide, box: Bbox, fill: str, text: str, text_color: str, size: float, font: Optional[str]):
    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(box.x), Emu(box.y), Emu(box.w), Emu(box.h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(fill)
    shape.line.fill.background()
    shape.shadow.inherit = False
    tf = shape.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Emu(0)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.bold = True
    r.font.color.rgb = RGBColor.from_string(text_color)
    if font:
        r.font.name = font
    return shape


def _items(oslide: OutlineSlide) -> list[SlideItem]:
    c = oslide.content
    if c.items:
        return list(c.items)
    if c.columns:
        return list(c.columns)
    if c.numbers:
        return [SlideItem(title=n.value, text=n.label, number=n.value) for n in c.numbers]
    return [SlideItem(title=b) for b in c.bullets]


def render_synth(builder: DeckBuilder, plan_slide: LayoutSlide, oslide: OutlineSlide, manifest: TemplateManifest, ws: TemplateWorkspace, outline: DeckOutline) -> tuple[Slide, list[str]]:
    warnings: list[str] = []
    family = _family_for(oslide, manifest)
    pal = _Palette(manifest, family)
    layout = _layout_for(builder, manifest, family, oslide.kind)
    slide = builder.prs.slides.add_slide(layout)
    builder.created.append(slide)
    t = manifest.tokens
    typo = t.typography
    W, H = builder.slide_w, builder.slide_h
    safe = t.spacing.safe_area
    sx, sy, sw, sh = int(safe.x * W), int(safe.y * H), int(safe.w * W), int(safe.h * H)
    scale = [s.size_pt for s in typo.scale]
    font = typo.primary_family
    h1, title_color, title_bold, title_font = _title_style(manifest, family, pal)
    body = typo.size_for("body", 14.0)
    h2 = typo.size_for("h2", body * 1.25)
    small = typo.size_for("small", body * 0.85)
    display = typo.size_for("display", h1 * 1.8)

    # keep only the title placeholder (fill it) — everything else is drawn from tokens
    title_ph = None
    for shp in list(slide.shapes):
        if shp.is_placeholder and shp.placeholder_format.type is not None and str(shp.placeholder_format.type).split(".")[-1].split(" ")[0] in ("TITLE", "CENTER_TITLE"):
            title_ph = shp
        else:
            shp._element.getparent().remove(shp._element)
    comp = plan_slide.composition or "bullets"
    c = oslide.content
    title_h = int(H * (0.16 if comp not in ("title", "section", "thanks") else 0.3))
    if title_ph is not None and comp not in ("title", "section", "thanks"):
        fill_text(title_ph._element, [ParagraphSpec(oslide.headline)])
        tb = title_ph
        y_after = int(title_ph.top + title_ph.height) if title_ph.top is not None else sy + title_h
    elif comp not in ("title", "section", "thanks"):
        if title_ph is not None:
            title_ph._element.getparent().remove(title_ph._element)
        _textbox(slide, Bbox(x=sx, y=sy, w=sw, h=title_h), [ParagraphSpec(oslide.headline)], size=h1, color=title_color, font=title_font, bold=title_bold, scale=scale, anchor="t")
        y_after = sy + title_h
    else:
        if title_ph is not None:
            title_ph._element.getparent().remove(title_ph._element)
        y_after = sy
    top = y_after + int(H * 0.02)
    avail_h = sy + sh - top
    gap = int((t.spacing.gutter or 0.03) * W)

    if comp in ("title", "section", "thanks"):
        box = Bbox(x=sx, y=int(H * 0.30), w=int(sw * 0.8), h=int(H * 0.3))
        _textbox(slide, box, [ParagraphSpec(oslide.headline)], size=max(h1, display * 0.8) if comp == "title" else h1, color=title_color, font=title_font, bold=title_bold, scale=scale, anchor="b")
        sub = oslide.subtitle or (oslide.section if comp == "section" else None)
        if sub:
            _textbox(slide, Bbox(x=sx, y=int(H * 0.62), w=int(sw * 0.8), h=int(H * 0.16)), [ParagraphSpec(sub)], size=h2, color=pal.text2, font=font, scale=scale)
        return slide, warnings

    if comp == "bullets" or (comp in ("image_text",) and not c.image_hint):
        paras = [ParagraphSpec(b, bullet=True) for b in c.bullets] or [ParagraphSpec(p, bullet=False) for p in c.paragraphs] or [ParagraphSpec(i.title, bullet=True) for i in _items(oslide)]
        if oslide.subtitle:
            paras = [ParagraphSpec(oslide.subtitle, bullet=False, bold=True)] + paras
        _textbox(slide, Bbox(x=sx, y=top, w=int(sw * 0.9), h=avail_h), paras, size=body, color=pal.text, font=font, scale=scale, line_spacing=typo.line_spacing)
        return slide, warnings

    if comp == "image_text":
        path = pick_asset(manifest, ws, c.image_hint)
        img_w = int(sw * 0.42)
        if path:
            insert_picture(slide, Bbox(x=sx, y=top, w=img_w, h=avail_h), path)
            x_text = sx + img_w + gap
        else:
            x_text = sx
        paras = [ParagraphSpec(b, bullet=True) for b in c.bullets] or [ParagraphSpec(p) for p in c.paragraphs]
        _textbox(slide, Bbox(x=x_text, y=top, w=sx + sw - x_text, h=avail_h), paras, size=body, color=pal.text, font=font, scale=scale)
        return slide, warnings

    if comp in ("cards", "process", "agenda", "comparison", "two_column"):
        items = _items(oslide)
        n = max(len(items), 1)
        cols = n if n <= 4 else math.ceil(n / 2)
        rows = math.ceil(n / cols)
        if comp in ("two_column", "comparison"):
            cols, rows = min(n, 3), 1
        cw = int((sw - gap * (cols - 1)) / cols)
        ch = int((avail_h - gap * (rows - 1)) / rows)
        for i, item in enumerate(items):
            r_, c_ = divmod(i, cols)
            box = Bbox(x=sx + c_ * (cw + gap), y=top + r_ * (ch + gap), w=cw, h=ch)
            if comp in ("cards", "comparison") and (pal.card_fill or pal.card_line):
                _rect(slide, box, pal.card_fill, pal.card_line if not pal.card_fill else None, pal.radius)
            inset = int(cw * 0.07)
            head_h = int(ch * 0.3)
            y_head = box.y + inset
            if comp in ("process", "agenda"):
                d = int(min(cw, ch) * 0.28)
                _circle(slide, Bbox(x=box.x, y=box.y, w=d, h=d), pal.accent, str(i + 1), "FFFFFF" if contrast_ratio("FFFFFF", pal.accent) >= 3 else pal.text, max(small, d / 12700 * 0.45), font)
                y_head = box.y + d + int(H * 0.015)
                inset = 0
                head_h = int(ch * 0.22)
            _textbox(slide, Bbox(x=box.x + inset, y=y_head, w=cw - 2 * inset, h=head_h), [ParagraphSpec(item.title)], size=h2 if comp != "agenda" else h2, color=pal.accent if comp in ("cards", "comparison") else pal.text, font=font, bold=True, scale=scale, anchor="t")
            body_paras = [ParagraphSpec(b, bullet=True) for b in item.bullets] or ([ParagraphSpec(item.text)] if item.text else [])
            if body_paras:
                _textbox(slide, Bbox(x=box.x + inset, y=y_head + head_h, w=cw - 2 * inset, h=box.y2 - (y_head + head_h) - inset), body_paras, size=body, color=pal.text, font=font, scale=scale, line_spacing=typo.line_spacing)
        return slide, warnings

    if comp in ("stat_row", "big_number"):
        nums = c.numbers
        n = max(len(nums), 1)
        if comp == "big_number" or n == 1:
            num = nums[0] if nums else None
            if num:
                _textbox(slide, Bbox(x=sx, y=top, w=int(sw * 0.5), h=int(avail_h * 0.55)), [ParagraphSpec(num.value)], size=display, color=pal.accent, font=font, bold=True, anchor="b", scale=scale, fit=False)
                _textbox(slide, Bbox(x=sx, y=top + int(avail_h * 0.57), w=int(sw * 0.5), h=int(avail_h * 0.3)), [ParagraphSpec(num.label)], size=h2, color=pal.text2, font=font, scale=scale)
            if c.paragraphs or c.bullets:
                paras = [ParagraphSpec(b, bullet=True) for b in c.bullets] or [ParagraphSpec(p) for p in c.paragraphs]
                _textbox(slide, Bbox(x=sx + int(sw * 0.55), y=top, w=int(sw * 0.45), h=avail_h), paras, size=body, color=pal.text, font=font, scale=scale)
            return slide, warnings
        cw = int((sw - gap * (n - 1)) / n)
        for i, num in enumerate(nums):
            x = sx + i * (cw + gap)
            _textbox(slide, Bbox(x=x, y=top, w=cw, h=int(avail_h * 0.45)), [ParagraphSpec(num.value)], size=display * 0.8, color=pal.accent, font=font, bold=True, anchor="b", scale=scale)
            _textbox(slide, Bbox(x=x, y=top + int(avail_h * 0.47), w=cw, h=int(avail_h * 0.35)), [ParagraphSpec(num.label)], size=body, color=pal.text2, font=font, scale=scale)
        return slide, warnings

    if comp == "chart_text" and c.chart is not None:
        has_text = bool(c.paragraphs or c.bullets)
        chart_w = int(sw * (0.62 if has_text else 1.0))
        try:
            add_chart(slide, Bbox(x=sx, y=top, w=chart_w, h=avail_h), c.chart, outline, manifest.components.chart_style, typo, text_hex=pal.text, neutral_hex=t.color_for("neutral.1"))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"chart failed: {str(e)[:120]}")
        if has_text:
            paras = [ParagraphSpec(b, bullet=True) for b in c.bullets] or [ParagraphSpec(p) for p in c.paragraphs]
            _textbox(slide, Bbox(x=sx + chart_w + gap, y=top, w=sw - chart_w - gap, h=avail_h), paras, size=body, color=pal.text, font=font, scale=scale)
        return slide, warnings

    if comp == "table" and c.table is not None:
        rows = len(c.table.rows) + 1
        tbl_h = min(avail_h, int(rows * H * 0.075))
        try:
            add_table(slide, Bbox(x=sx, y=top, w=sw, h=tbl_h), c.table, manifest.components.table_style, typo)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"table failed: {str(e)[:120]}")
        if c.paragraphs and tbl_h < avail_h - int(H * 0.08):
            _textbox(slide, Bbox(x=sx, y=top + tbl_h + int(H * 0.02), w=sw, h=avail_h - tbl_h - int(H * 0.02)), [ParagraphSpec(p) for p in c.paragraphs], size=small, color=pal.text2, font=font, scale=scale)
        return slide, warnings

    if comp == "quote" and c.quote:
        _textbox(slide, Bbox(x=sx, y=top, w=int(sw * 0.85), h=int(avail_h * 0.65)), [ParagraphSpec("«" + c.quote.strip("«»\"") + "»")], size=h2 * 1.15, color=pal.text, font=font, scale=scale, anchor="ctr")
        if c.quote_author:
            _textbox(slide, Bbox(x=sx, y=top + int(avail_h * 0.68), w=int(sw * 0.85), h=int(avail_h * 0.2)), [ParagraphSpec(c.quote_author)], size=small, color=pal.accent, font=font, scale=scale)
        return slide, warnings

    # fallback: bullets
    paras = [ParagraphSpec(b, bullet=True) for b in c.bullets] or [ParagraphSpec(p) for p in c.paragraphs] or [ParagraphSpec(i.title, bullet=True) for i in _items(oslide)]
    if paras:
        _textbox(slide, Bbox(x=sx, y=top, w=int(sw * 0.9), h=avail_h), paras, size=body, color=pal.text, font=font, scale=scale)
    else:
        warnings.append("empty slide content")
    return slide, warnings
