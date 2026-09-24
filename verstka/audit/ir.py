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
from verstka.schemas.deck_ir import DeckIR, IRChart, IRChartSeries, IRElement, IRParagraph, IRPointLabel, IRRun, IRSlide, IRTable, IRTableCell

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


def build_deck_ir(pptx: Path | str, with_images: bool = True) -> DeckIR:
    pkg = PptxPackage.open(pptx)
    W, H = pkg.slide_size
    ir = DeckIR(source=str(pptx), slide_w=W, slide_h=H, embedded_fonts=pkg.embedded_fonts)
    ir.layout_parts = sorted({p for p in pkg.part_names if re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", p)})
    img_cache: dict[str, Optional[tuple[int, int]]] = {}
    for i, part in enumerate(pkg.slide_parts, 1):
        ctx = SlideContext(pkg, part)
        shapes = extract_shapes(pkg, part, ctx)
        fam, bg = slide_family(pkg, part, ctx, shapes)
        notes = pkg.notes_text(part)
        m = OUTLINE_MARK_RE.search(notes)
        slide = IRSlide(index=i, layout_part=ctx.layout_part, family=fam, background_hex=bg, notes=OUTLINE_MARK_RE.sub("", notes).strip(), outline_id=m.group(1) if m else None)
        rels = pkg.rels(part)
        for s in shapes:
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
            el = IRElement(
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
            if etype == "picture" and with_images:
                if s.image_part not in img_cache:
                    img_cache[s.image_part] = _image_size(pkg, s.image_part)
                el.image_size = img_cache[s.image_part]
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
    pkg.close()
    return ir
