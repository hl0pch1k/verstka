"""Build a DeckIR from any PPTX by reusing the template shape extractor."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional

from lxml import etree

from verstka.analysis.shapes import SlideContext, extract_shapes, slide_family
from verstka.analysis.xmlns import NS, find, findall, q
from verstka.ingest.package import PptxPackage
from verstka.schemas.common import ShapeKind
from verstka.schemas.deck_ir import DeckIR, IRChart, IRChartSeries, IRElement, IRParagraph, IRPictureCells, IRPointLabel, IRRun, IRSlide, IRTable, IRTableCell

OUTLINE_MARK_RE = re.compile(r"\[verstka:([A-Za-z0-9_\-]+)\]")

_CHART_TAGS = {"barChart": "bar", "bar3DChart": "bar", "lineChart": "line", "line3DChart": "line", "areaChart": "area", "pieChart": "pie", "pie3DChart": "pie", "doughnutChart": "doughnut", "scatterChart": "scatter", "radarChart": "radar"}


def _srgb(el: Optional[etree._Element], path: str) -> Optional[str]:
    c = find(el, path) if el is not None else None
    v = c.get("val") if c is not None else None
    return v.upper() if v and len(v) == 6 else None


def _text_style(holder: Optional[etree._Element]) -> tuple[Optional[str], Optional[bool], Optional[float]]:
    """(colour, bold, size) of the default run properties in a c:txPr under `holder`."""
    d = find(holder, "c:txPr/a:p/a:pPr/a:defRPr") if holder is not None else None
    if d is None:
        return None, None, None
    b = d.get("b")
    sz = d.get("sz")
    return _srgb(d, "a:solidFill/a:srgbClr"), (b in ("1", "true")) if b is not None else None, (int(sz) / 100 if sz and sz.isdigit() else None)


def _on(el: Optional[etree._Element], path: str) -> Optional[bool]:
    f = find(el, path) if el is not None else None
    return None if f is None else f.get("val") in ("1", "true", None)


def _series_style(ser: etree._Element, series: IRChartSeries) -> None:
    """Paint and label overrides of one c:ser, as a chart made by verstka.rendering.charts writes them."""
    sp = find(ser, "c:spPr")
    fill = _srgb(sp, "a:solidFill/a:srgbClr")
    line = _srgb(sp, "a:ln/a:solidFill/a:srgbClr")
    series.color = series.color or fill or line
    series.outline_only = sp is not None and find(sp, "a:noFill") is not None and line is not None
    series.dashed = sp is not None and find(sp, "a:ln/a:prstDash") is not None and find(sp, "a:ln/a:prstDash").get("val") not in ("solid", None)
    for dpt in findall(ser, "c:dPt"):
        idx = find(dpt, "c:idx")
        col = _srgb(dpt, "c:spPr/a:solidFill/a:srgbClr")
        if idx is not None and col:
            series.point_colors[int(idx.get("val"))] = col
    dl = find(ser, "c:dLbls")
    if dl is None:
        return
    series.labels_shown = _on(dl, "c:showVal")
    nf = find(dl, "c:numFmt")
    series.label_format = nf.get("formatCode") if nf is not None else series.label_format
    series.label_color, series.label_bold, series.label_size_pt = _text_style(dl)
    for lbl in findall(dl, "c:dLbl"):
        idx = find(lbl, "c:idx")
        if idx is None:
            continue
        o = IRPointLabel(deleted=bool(_on(lbl, "c:delete")))
        if not o.deleted:
            nf = find(lbl, "c:numFmt")
            o.format = nf.get("formatCode") if nf is not None else None
            o.color, o.bold, o.size_pt = _text_style(lbl)
            o.series_name = bool(_on(lbl, "c:showSerName"))
            pos = find(lbl, "c:dLblPos")
            o.position = pos.get("val") if pos is not None else None
            if not _on(lbl, "c:showVal") and not o.series_name:
                o.deleted = True
        series.point_labels[int(idx.get("val"))] = o


def _chart_from_part(pkg: PptxPackage, chart_part: str) -> Optional[IRChart]:
    if not pkg.exists(chart_part):
        return None
    root = pkg.xml(chart_part)
    plot = find(root, ".//c:plotArea")
    if plot is None:
        return None
    ctype = "other"
    chart_el = None
    for child in plot:
        tag = etree.QName(child).localname
        if tag in _CHART_TAGS:
            ctype = _CHART_TAGS[tag]
            chart_el = child
            if tag.startswith("bar"):
                bd = find(child, "c:barDir")
                ctype = "column" if (bd is not None and bd.get("val") == "col") else "bar"
            break
    if chart_el is None:
        return None
    series: list[IRChartSeries] = []
    categories: list[str] = []
    colors: list[str] = []
    for ser in findall(chart_el, "c:ser"):
        name = "".join(t.text or "" for t in ser.iter(q("c:v")) if t.getparent() is not None and etree.QName(t.getparent()).localname == "pt" and etree.QName(t.getparent().getparent()).localname == "strCache" and etree.QName(t.getparent().getparent().getparent()).localname == "strRef" and etree.QName(t.getparent().getparent().getparent().getparent()).localname == "tx")
        if not name:
            tx = find(ser, "c:tx")
            name = "".join(t.text or "" for t in tx.iter(q("c:v"))) if tx is not None else f"series{len(series) + 1}"
        vals: list[float] = []
        val = find(ser, "c:val")
        if val is not None:
            for pt in val.iter(q("c:pt")):
                v = find(pt, "c:v")
                try:
                    vals.append(float(v.text)) if v is not None and v.text else None
                except ValueError:
                    pass
        if not categories:
            cat = find(ser, "c:cat")
            if cat is not None:
                categories = ["".join(find(pt, "c:v").text or "" for _ in [0]) if find(pt, "c:v") is not None else "" for pt in cat.iter(q("c:pt"))]
        sp = find(ser, "c:spPr")
        clr = find(sp, "a:solidFill/a:srgbClr") if sp is not None else None
        if clr is not None and clr.get("val"):
            colors.append(clr.get("val").upper())
        series.append(IRChartSeries(name=name, values=vals))
    dlbls = find(chart_el, "c:dLbls")
    has_labels = False
    if dlbls is not None:
        sv = find(dlbls, "c:showVal")
        has_labels = sv is not None and sv.get("val") in ("1", "true")
    if not has_labels:
        for ser in findall(chart_el, "c:ser"):
            sv = find(ser, "c:dLbls/c:showVal")
            if sv is not None and sv.get("val") in ("1", "true"):
                has_labels = True
                break
    has_legend = find(root, ".//c:legend") is not None
    val_ax = find(plot, "c:valAx")
    has_val_axis = val_ax is not None and (find(val_ax, "c:delete") is None or find(val_ax, "c:delete").get("val") in ("0", "false"))
    nf = find(chart_el, "c:dLbls/c:numFmt")
    for ser, s in zip(findall(chart_el, "c:ser"), series):
        _series_style(ser, s)
    # an area drawn with its top edge as a line series over it: the edge carries the area's labels
    if ctype == "area":
        nxt = chart_el.getnext()
        if nxt is not None and etree.QName(nxt).localname == "lineChart":
            for ser, s in zip(findall(nxt, "c:ser"), series):
                s.point_labels = {}
                _series_style(ser, s)
    title = " ".join(t.text or "" for t in root.iter(q("a:t")) if any(etree.QName(a).localname == "title" for a in t.iterancestors())).strip() or None
    cat_ax = find(plot, "c:catAx")
    orient = find(cat_ax, "c:scaling/c:orientation") if cat_ax is not None else None
    return IRChart(
        type=ctype, categories=categories, series=series, has_data_labels=has_labels, has_legend=has_legend, has_value_axis=has_val_axis,
        colors=colors, number_format=nf.get("formatCode") if nf is not None else None, title=title,
        series_labels=any(e.get("val") in ("1", "true") for e in plot.iter(q("c:showSerName"))),
        axis_color=_text_style(cat_ax)[0] if cat_ax is not None else None,
        rule_color=_srgb(cat_ax, "c:spPr/a:ln/a:solidFill/a:srgbClr") if cat_ax is not None else None,
        reversed_categories=orient is not None and orient.get("val") == "maxMin",
    )


def _table_from_frame(el: etree._Element) -> Optional[IRTable]:
    tbl = find(el, "a:graphic/a:graphicData/a:tbl")
    if tbl is None:
        return None
    rows: list[list[str]] = []
    cells: list[list[IRTableCell]] = []
    for tr in findall(tbl, "a:tr"):
        rows.append(["".join(t.text or "" for t in tc.iter(q("a:t"))) for tc in findall(tr, "a:tc")])
        cells.append([_table_cell(tc) for tc in findall(tr, "a:tc")])
    header_fill = None
    first_tc = find(tbl, "a:tr/a:tc/a:tcPr/a:solidFill/a:srgbClr")
    if first_tc is not None:
        header_fill = (first_tc.get("val") or "").upper() or None
    cols = [int(g.get("w") or 0) for g in findall(tbl, "a:tblGrid/a:gridCol")]
    return IRTable(rows=rows, header_fill_hex=header_fill, col_widths_emu=cols, cells=cells)


def _table_cell(tc: etree._Element) -> IRTableCell:
    cell = IRTableCell()
    tcPr = find(tc, "a:tcPr")
    if tcPr is not None:
        for attr, name in (("marL", "mar_l_pt"), ("marR", "mar_r_pt")):
            v = tcPr.get(attr)
            if v is not None and v.lstrip("-").isdigit():
                setattr(cell, name, int(v) / 12700)
        clr = find(tcPr, "a:solidFill/a:srgbClr")
        if clr is not None:
            alpha = find(clr, "a:alpha")
            if alpha is None or int(alpha.get("val") or 100000) >= 50000:
                cell.fill_hex = _srgb(tcPr, "a:solidFill/a:srgbClr")
    for r in tc.iter(q("a:r")):
        t = find(r, "a:t")
        if t is None or not (t.text or "").strip():
            continue
        rPr = find(r, "a:rPr")
        if rPr is not None:
            if (rPr.get("sz") or "").isdigit():
                cell.size_pt = int(rPr.get("sz")) / 100
            cell.bold = rPr.get("b") in ("1", "true")
            cell.color_hex = _srgb(rPr, "a:solidFill/a:srgbClr")
        break
    return cell


def _image_size(pkg: PptxPackage, part: Optional[str]) -> Optional[tuple[int, int]]:
    if not part or not pkg.exists(part) or part.lower().endswith(".svg"):
        return None
    try:
        from PIL import Image

        with Image.open(io.BytesIO(pkg.read(part))) as im:
            return im.width, im.height
    except Exception:  # noqa: BLE001
        return None


def _ir_element(s, W: int, H: int) -> IRElement:
    """One IRElement from an extracted shape (geometry, text, paint; charts/tables/images are filled by the caller)."""
    if s.kind == ShapeKind.pic:
        etype = "picture"
    elif s.kind == ShapeKind.graphic_frame:
        etype = "chart" if s.frame_kind == "chart" else ("table" if s.frame_kind == "table" else "other")
    elif s.kind == ShapeKind.connector:
        etype = "connector"
    elif s.kind == ShapeKind.group:
        etype = "group"
    else:
        etype = "text" if (s.text is not None and s.plain_text.strip()) else "shape"
    paragraphs = []
    if s.text is not None:
        for p in s.text.paragraphs:
            paragraphs.append(IRParagraph(text=p.text, bullet=p.has_bullet, level=p.level, align=p.align, line_spacing=p.line_spacing, runs=[IRRun(text=r.text, font=r.font, size_pt=r.size_pt, bold=r.bold, italic=r.italic, color_hex=r.color_hex) for r in p.runs]))
    return IRElement(
        id=s.id,
        type=etype,
        bbox=s.bbox,
        bbox_frac=s.bbox.to_frac(W, H),
        paragraphs=paragraphs,
        fill_hex=s.fill_hex,
        fill_alpha=s.fill_alpha,
        line_hex=s.line_hex,
        image_part=s.image_part,
        crop=s.crop,
        native_kind=s.frame_kind,
        is_placeholder=s.is_placeholder,
        ph_type=s.ph_type,
        name=s.name,
        z=s.z,
        nested=bool(s.group_path),
        autofit=s.text.autofit if s.text else None,
        insets_emu=s.text.insets_emu if s.text else (91440, 45720, 91440, 45720),
        anchor=s.text.anchor if s.text else None,
        wrap=s.text.wrap if s.text else True,
        geometry=s.geometry,
        corner_radius=s.corner_radius,
        rotation=s.rotation,
    )


def _shows_master(root: Optional[etree._Element]) -> bool:
    return root is None or root.get("showMasterSp") not in ("0", "false")


def _part_template_elements(pkg: PptxPackage, part: str, ctx: SlideContext, source: str, W: int, H: int) -> list[IRElement]:
    """The non-placeholder shapes of a layout or master part as IR elements (a layout's placeholders are prompts the
    slide replaces with its own). Pictures and picture/gradient/pattern fills get their colour, opacity and busyness
    from the analysis' painted layers."""
    import copy as _copy

    pctx = _copy.copy(ctx)
    pctx.slide_part = part  # picture relationships resolve against the part that holds them
    paint: dict[str, object] = {}
    try:
        from verstka.analysis.ground import _part_layers

        for la in _part_layers(pkg, part, ctx, source, 0):
            if la.shape_id:
                paint[la.shape_id] = la
    except Exception:  # noqa: BLE001 - paint details are a refinement; geometry still works without them
        paint = {}
    out: list[IRElement] = []
    for s in extract_shapes(pkg, part, pctx):
        if s.is_placeholder or s.bbox.w <= 0 or s.bbox.h <= 0:
            continue
        e = _ir_element(s, W, H)
        e.id = f"{source}:{s.id}"
        e.source = source
        la = paint.get(s.id)
        if la is not None:
            # what the shape really paints: a gradient's mean, a pattern's blend, a picture's median
            if getattr(la, "hex", None):
                e.fill_hex = la.hex
            e.busy = bool(getattr(la, "busy", False))
            e.opaque = bool(getattr(la, "opaque", True))
            e.paint_kind = getattr(la, "kind", None)
        elif e.type == "picture":
            e.opaque = False  # an unreadable picture (vector): no colour we can trust
            e.paint_kind = "image"
        if e.type == "picture" and s.image_part:
            raster = _raster_part(pkg, part, s.element) or s.image_part  # an SVG picture carries a PNG fallback
            e.cells = (_photo_cells if _full_slide(e.bbox_frac) else _picture_cells)(pkg, raster, s.crop, s.element)
            ob = _opaque_box(pkg, raster, s.crop, s.bbox) if e.cells is None else None
            if ob is not None and (ob.w, ob.h) != (s.bbox.w, s.bbox.h):
                # a transparent PNG laid over the slide paints only its opaque pixels (a glass cube, a supergraphic)
                e.bbox, e.bbox_frac = ob, ob.to_frac(W, H)
        if s.element is not None and e.type in ("shape", "text"):
            try:
                e.outline = shape_outline(s.element, s.bbox, s.rotation)
            except Exception:  # noqa: BLE001 - the box stands for the shape
                e.outline = None
            spPr = s.element.find(q("p:spPr"))
            gf = spPr.find(q("a:gradFill")) if spPr is not None else None
            if gf is not None:
                # a gradient panel is not one colour: what lies under a text is the gradient at the text's place
                try:
                    e.cells = gradient_cells(ctx.resolver, gf, s.bbox.w, s.bbox.h)
                except Exception:  # noqa: BLE001 - the mean colour stands for the gradient
                    e.cells = None
        out.append(e)
    return out


_OPAQUE: dict[tuple, Optional[tuple[float, float, float, float]]] = {}


def _raster_part(pkg: PptxPackage, part: str, el: Optional[etree._Element]) -> Optional[str]:
    """The raster picture an a:blip embeds (the PNG fallback of an SVG picture)."""
    blip = el.find(".//" + q("a:blip")) if el is not None else None
    rid = blip.get(q("r:embed")) if blip is not None else None
    try:
        return pkg.target_of(part, rid) if rid else None
    except Exception:  # noqa: BLE001
        return None


_CELLS: dict[tuple, Optional[IRPictureCells]] = {}
CELLS_W, CELLS_H = 24, 14


def _stop_alpha(clr: etree._Element) -> float:
    a = clr.find(q("a:alpha"))
    try:
        return max(0.0, min(1.0, int(a.get("val") or 100000) / 100000.0)) if a is not None else 1.0
    except ValueError:
        return 1.0


def gradient_cells(resolver, grad: etree._Element, w: float, h: float) -> Optional[IRPictureCells]:
    """`IRPictureCells` of a gradient fill over its shape's box: per cell the gradient's colour and opacity (stop
    alpha) at the cell's centre and the luminance spread of its corners; None when no stop resolves."""
    from verstka.rendering.layers import gradient_at, gradient_position
    from verstka.schemas.common import hex_to_rgb

    stops = []
    for gs in grad.findall(q("a:gsLst") + "/" + q("a:gs")):
        if not len(gs):
            continue
        hx = resolver.resolve_color(gs[0])
        if not hx:
            continue
        try:
            pos = int(gs.get("pos") or 0) / 100000.0
        except ValueError:
            pos = 0.0
        stops.append((pos, tuple(float(c) for c in hex_to_rgb(hx)), _stop_alpha(gs[0])))
    if not stops:
        return None
    stops.sort(key=lambda s: s[0])
    alpha, hexes, std = [], [], []
    for j in range(CELLS_H):
        for i in range(CELLS_W):
            u, v = (i + 0.5) / CELLS_W, (j + 0.5) / CELLS_H
            rgb, a = gradient_at(stops, gradient_position(grad, u, v, w, h))
            lums = []
            for du, dv in ((-0.5, -0.5), (0.5, -0.5), (-0.5, 0.5), (0.5, 0.5)):
                c, _ = gradient_at(stops, gradient_position(grad, u + du / CELLS_W, v + dv / CELLS_H, w, h))
                lums.append(0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])
            mean = sum(lums) / 4
            alpha.append(round(a, 3))
            hexes.append("%02X%02X%02X" % tuple(int(round(min(max(x, 0), 255))) for x in rgb))
            std.append(round((sum((x - mean) ** 2 for x in lums) / 4) ** 0.5, 1))
    return IRPictureCells(w=CELLS_W, h=CELLS_H, alpha=alpha, hex=hexes, std=std)


def _picture_cells(pkg: PptxPackage, image_part: str, crop, el: Optional[etree._Element]) -> Optional[IRPictureCells]:
    """`IRPictureCells` of a picture over its whole (unrotated) box, crop and flips applied; None when unreadable."""
    if not image_part or image_part.lower().endswith((".svg", ".emf", ".wmf")) or not pkg.exists(image_part):
        return None
    xfrm = el.find(q("p:spPr") + "/" + q("a:xfrm")) if el is not None else None
    flip_h = xfrm is not None and xfrm.get("flipH") in ("1", "true")
    flip_v = xfrm is not None and xfrm.get("flipV") in ("1", "true")
    l, t, r, b = crop or (0.0, 0.0, 0.0, 0.0)
    key = (str(getattr(pkg, "path", "")), image_part, (l, t, r, b), flip_h, flip_v)
    if key not in _CELLS:
        from verstka.rendering.layers import image_cells  # one grid for the audit and the renderer (round 4.1, C3-2)

        got = None
        try:
            vals = image_cells(pkg.read(image_part), (l, t, r, b), flip_h, flip_v)
        except Exception:  # noqa: BLE001
            vals = None
        if vals is not None:
            alpha, hexes, std = vals
            got = IRPictureCells(w=CELLS_W, h=CELLS_H, alpha=alpha, hex=hexes, std=std)
        _CELLS[key] = got
    return _CELLS[key]


_FINE: dict[tuple, Optional[list[float]]] = {}


def _photo_cells(pkg: PptxPackage, image_part: str, crop, el: Optional[etree._Element]) -> Optional[IRPictureCells]:
    """`_picture_cells` of a photo ground (a picture covering ≥ 85 % of the slide) with its fine stdev grid
    (`layers.image_fine_std`): content_over_art tells a line running onto the photo's busy part from a line standing
    just above a blot in the same coarse cell (round 4.1)."""
    cells = _picture_cells(pkg, image_part, crop, el)
    if cells is None:
        return None
    xfrm = el.find(q("p:spPr") + "/" + q("a:xfrm")) if el is not None else None
    flip_h = xfrm is not None and xfrm.get("flipH") in ("1", "true")
    flip_v = xfrm is not None and xfrm.get("flipV") in ("1", "true")
    l, t, r, b = crop or (0.0, 0.0, 0.0, 0.0)
    key = (str(getattr(pkg, "path", "")), image_part, (l, t, r, b), flip_h, flip_v)
    if key not in _FINE:
        from verstka.rendering.layers import image_fine_std

        try:
            _FINE[key] = image_fine_std(pkg.read(image_part), (l, t, r, b), flip_h, flip_v)
        except Exception:  # noqa: BLE001
            _FINE[key] = None
    fine = _FINE[key]
    return cells.model_copy(update={"fine_std": list(fine)}) if fine else cells


def _full_slide(f) -> bool:
    return max(0.0, min(f.x2, 1.0) - max(f.x, 0.0)) * max(0.0, min(f.y2, 1.0) - max(f.y, 0.0)) >= 0.85


def _opaque_box(pkg: PptxPackage, image_part: str, crop, box):
    """The part of a picture's box its opaque pixels cover (alpha > 40), crop respected; None when unknown."""
    from verstka.schemas.common import Bbox

    if not image_part or image_part.lower().endswith((".svg", ".emf", ".wmf")) or not pkg.exists(image_part):
        return None
    l, t, r, b = crop or (0.0, 0.0, 0.0, 0.0)
    key = (str(getattr(pkg, "path", "")), image_part, (l, t, r, b))
    if key not in _OPAQUE:
        frac = None
        try:
            from PIL import Image

            with Image.open(io.BytesIO(pkg.read(image_part))) as im:
                if "A" in im.getbands():
                    iw, ih = im.size
                    vis = (int(l * iw), int(t * ih), max(int((1 - r) * iw), int(l * iw) + 1), max(int((1 - b) * ih), int(t * ih) + 1))
                    a = im.getchannel("A").crop(vis)
                    bb = a.point(lambda v: 255 if v > 40 else 0).getbbox()
                    vw, vh = vis[2] - vis[0], vis[3] - vis[1]
                    frac = (bb[0] / vw, bb[1] / vh, (bb[2] - bb[0]) / vw, (bb[3] - bb[1]) / vh) if bb else (0.0, 0.0, 0.0, 0.0)
        except Exception:  # noqa: BLE001
            frac = None
        _OPAQUE[key] = frac
    frac = _OPAQUE[key]
    if frac is None:
        return None
    return Bbox(x=int(box.x + frac[0] * box.w), y=int(box.y + frac[1] * box.h), w=max(int(frac[2] * box.w), 0), h=max(int(frac[3] * box.h), 0))


def _num(v: Optional[str]) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def _ellipse(w: float, h: float, n: int = 24) -> list[tuple[float, float]]:
    import math

    return [(w / 2 + w / 2 * math.cos(2 * math.pi * k / n), h / 2 + h / 2 * math.sin(2 * math.pi * k / n)) for k in range(n)]


def _preset_outline(prst: str, w: float, h: float, geom: etree._Element) -> Optional[list[list[tuple[float, float]]]]:
    adj = None
    for gd in geom.iter(q("a:gd")):
        f = (gd.get("fmla") or "").split()
        if gd.get("name") == "adj" and len(f) == 2 and f[0] == "val":
            adj = _num(f[1])
    if prst == "ellipse":
        return [_ellipse(w, h)]
    if prst == "triangle":
        a = (adj if adj is not None else 50000) / 100000.0
        return [[(a * w, 0.0), (w, h), (0.0, h)]]
    if prst == "rtTriangle":
        return [[(0.0, 0.0), (w, h), (0.0, h)]]
    if prst == "diamond":
        return [[(w / 2, 0.0), (w, h / 2), (w / 2, h), (0.0, h / 2)]]
    return None


def _path_points(path: etree._Element) -> Optional[list[list[tuple[float, float]]]]:
    """The vertices of one a:path (curves by their end and control points, arcs sampled); None when a coordinate is
    a guide name rather than a number."""
    import math

    polys: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    for cmd in path:
        name = etree.QName(cmd).localname
        if name in ("moveTo", "lnTo", "cubicBezTo", "quadBezTo"):
            pts = []
            for pt in cmd.findall(q("a:pt")):
                x, y = _num(pt.get("x")), _num(pt.get("y"))
                if x is None or y is None:
                    return None
                pts.append((x, y))
            if name == "moveTo":
                if len(cur) > 2:
                    polys.append(cur)
                cur = pts[:1]
            else:
                cur.extend(pts)
        elif name == "arcTo" and cur:
            wr, hr, st, sw = (_num(cmd.get(k)) for k in ("wR", "hR", "stAng", "swAng"))
            if None in (wr, hr, st, sw):
                return None
            st, sw = math.radians(st / 60000.0), math.radians(sw / 60000.0)
            x0, y0 = cur[-1]
            cx, cy = x0 - wr * math.cos(st), y0 - hr * math.sin(st)
            for k in range(1, 9):
                a = st + sw * k / 8
                cur.append((cx + wr * math.cos(a), cy + hr * math.sin(a)))
        elif name == "close":
            if len(cur) > 2:
                polys.append(cur)
            cur = []
    if len(cur) > 2:
        polys.append(cur)
    return polys


def shape_outline(el: etree._Element, box, rotation: float = 0.0) -> Optional[list[list[tuple[int, int]]]]:
    """What a non-rectangular shape paints, as polygons in slide EMU (flips and rotation applied): ellipses,
    triangles, diamonds and freeforms (custGeom). None for rectangles and shapes whose box is what they paint."""
    import math

    spPr = el.find(q("p:spPr"))
    if spPr is None or box.w <= 0 or box.h <= 0:
        return None
    xfrm = spPr.find(q("a:xfrm"))
    flip_h = xfrm is not None and xfrm.get("flipH") in ("1", "true")
    flip_v = xfrm is not None and xfrm.get("flipV") in ("1", "true")
    w, h = float(box.w), float(box.h)
    prst = spPr.find(q("a:prstGeom"))
    polys: Optional[list[list[tuple[float, float]]]] = None
    if prst is not None:
        polys = _preset_outline(prst.get("prst") or "", w, h, prst)
    else:
        cust = spPr.find(q("a:custGeom"))
        if cust is None:
            return None
        polys = []
        for path in cust.iter(q("a:path")):
            if path.get("fill") == "none":
                continue  # a stroke only
            pw, ph = _num(path.get("w")) or w, _num(path.get("h")) or h
            pts = _path_points(path)
            if pts is None:
                return None
            polys += [[(x * w / pw if pw else 0.0, y * h / ph if ph else 0.0) for x, y in poly] for poly in pts]
        if not polys:
            return None
    if not polys:
        return None
    rot = math.radians(rotation or 0.0)
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    out = []
    for poly in polys:
        pts = []
        for x, y in poly:
            if flip_h:
                x = w - x
            if flip_v:
                y = h - y
            if rot:
                dx, dy = x - w / 2, y - h / 2
                x, y = w / 2 + dx * cos_r - dy * sin_r, h / 2 + dx * sin_r + dy * cos_r
            pts.append((int(box.x + x), int(box.y + y)))
        out.append(pts)
    return out


def _part_colors(pkg: PptxPackage, part: str, ctx: SlideContext) -> set[str]:
    """Every colour a layout or master part sets (fills, lines, txStyles, list styles), resolved through the theme."""
    out: set[str] = set()
    try:
        root = pkg.xml(part)
    except Exception:  # noqa: BLE001
        return out
    for tag in ("a:srgbClr", "a:schemeClr", "a:sysClr", "a:prstClr"):
        for el in root.iter(q(tag)):
            try:
                hx = ctx.resolver.resolve_color(el)
            except Exception:  # noqa: BLE001
                hx = None
            if hx and len(hx) == 6:
                out.add(hx.upper())
    return out


def shows_caps(s, ctx: SlideContext) -> bool:
    """Whether a slide text shape shows in capitals: `cap` on its first written run, else the level's `defRPr` of its
    own list style, then — for a placeholder — of the layout's and master's placeholder and the master's title/body
    style. The master's «other» style is not followed for plain text boxes (LibreOffice, which renders the audit's
    pictures, does not apply it to them)."""
    el = getattr(s, "element", None)
    txBody = el.find(q("p:txBody")) if el is not None else None
    if txBody is None:
        return False
    lvl, rpr = 0, None
    for para in txBody.findall(q("a:p")):
        run = next((r for r in para.findall(q("a:r")) if (r.findtext(q("a:t")) or "").strip()), None)
        if run is not None:
            rpr = run.find(q("a:rPr"))
            ppr = para.find(q("a:pPr"))
            try:
                lvl = int(ppr.get("lvl") or 0) if ppr is not None else 0
            except ValueError:
                lvl = 0
            break
    if rpr is not None and rpr.get("cap") is not None:
        return rpr.get("cap") in ("all", "small")
    sources = [txBody.find(q("a:lstStyle"))]
    if s.is_placeholder:
        try:
            lay, mas = ctx.inherited_placeholder(s.ph_type or "body", s.ph_idx)
        except Exception:  # noqa: BLE001
            lay = mas = None
        for ph in (lay, mas):
            if ph is not None:
                sources.append(ph.find(q("p:txBody") + "/" + q("a:lstStyle")))
        sources.append(ctx.master_style_for(s.ph_type, True))
    for src in sources:
        if src is None:
            continue
        for lv in src.findall(q(f"a:lvl{lvl + 1}pPr")):
            d = lv.find(q("a:defRPr"))
            if d is not None and d.get("cap") is not None:
                return d.get("cap") in ("all", "small")
    return False


def build_deck_ir(pptx: Path | str, with_images: bool = True) -> DeckIR:
    pkg = PptxPackage.open(pptx)
    W, H = pkg.slide_size
    ir = DeckIR(source=str(pptx), slide_w=W, slide_h=H, embedded_fonts=pkg.embedded_fonts)
    ir.layout_parts = sorted({p for p in pkg.part_names if re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", p)})
    img_cache: dict[str, Optional[tuple[int, int]]] = {}
    tpl_cache: dict[tuple[str, str], list[IRElement]] = {}
    tpl_colors: set[str] = set()
    colored_parts: set[str] = set()
    theme_fonts: list[str] = []
    for i, part in enumerate(pkg.slide_parts, 1):
        ctx = SlideContext(pkg, part)
        shapes = extract_shapes(pkg, part, ctx)
        kind, uncertain = None, False
        try:
            from verstka.analysis.ground import slide_ground

            g = slide_ground(pkg, part, ctx, shapes)
            fam, bg = g.family, g.hex
            kind, uncertain = getattr(g, "kind", None), bool(getattr(g, "uncertain", False))
        except Exception:  # noqa: BLE001 - the older resolver
            fam, bg = slide_family(pkg, part, ctx, shapes)
        notes = pkg.notes_text(part)
        m = OUTLINE_MARK_RE.search(notes)
        slide = IRSlide(index=i, layout_part=ctx.layout_part, family=fam, background_hex=bg, background_kind=kind, background_uncertain=uncertain, notes=OUTLINE_MARK_RE.sub("", notes).strip(), outline_id=m.group(1) if m else None)
        # what the layout and the master paint under the slide's own shapes
        if _shows_master(pkg.xml(part)):
            holders = []
            if ctx.master_part and _shows_master(ctx.layout):
                holders.append((ctx.master_part, "master"))
            if ctx.layout_part:
                holders.append((ctx.layout_part, "layout"))
            for hp, src in holders:
                key = (hp, ctx.master_part or "")
                if key not in tpl_cache:
                    try:
                        tpl_cache[key] = _part_template_elements(pkg, hp, ctx, src, W, H)
                    except Exception:  # noqa: BLE001
                        tpl_cache[key] = []
                slide.template_elements.extend(tpl_cache[key])
        for hp in (ctx.layout_part, ctx.master_part):
            if hp and hp not in colored_parts:
                colored_parts.add(hp)
                tpl_colors |= _part_colors(pkg, hp, ctx)
        if not theme_fonts:
            try:
                theme_fonts = [ctx.resolver.major_font or "", ctx.resolver.minor_font or ""]
            except Exception:  # noqa: BLE001
                theme_fonts = []
        rels = pkg.rels(part)
        for s in shapes:
            el = _ir_element(s, W, H)
            etype = el.type
            if etype == "text":
                try:
                    el.caps = shows_caps(s, ctx)
                except Exception:  # noqa: BLE001 - measured as typed
                    el.caps = False
            if etype == "picture" and with_images:
                if s.image_part not in img_cache:
                    img_cache[s.image_part] = _image_size(pkg, s.image_part)
                el.image_size = img_cache[s.image_part]
                if s.image_part and _full_slide(el.bbox_frac):
                    # a photo of the slide itself under everything (a cover's photo ground): its cells, so that a line
                    # running from its calm part onto its busy part is seen (content_over_art, round 4.1)
                    try:
                        el.cells = _photo_cells(pkg, s.image_part, s.crop, s.element)
                    except Exception:  # noqa: BLE001
                        el.cells = None
            if etype == "chart" and s.element is not None:
                c_el = find(s.element, "a:graphic/a:graphicData/c:chart")
                rid = c_el.get(q("r:id")) if c_el is not None else None
                target = rels[rid].target if rid and rid in rels else None
                if target:
                    el.chart = _chart_from_part(pkg, target)
            if etype == "table" and s.element is not None:
                el.table = _table_from_frame(s.element)
            slide.elements.append(el)
        ir.slides.append(slide)
    ir.template_colors = sorted(tpl_colors)
    ir.theme_fonts = theme_fonts
    pkg.close()
    return ir
