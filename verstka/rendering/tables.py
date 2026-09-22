"""Native PowerPoint tables styled from template tokens."""

from __future__ import annotations

import re
from typing import Optional

from lxml import etree
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.slide import Slide
from pptx.util import Emu, Pt

from verstka.analysis.xmlns import q
from verstka.schemas.common import Bbox
from verstka.schemas.outline import TableData
from verstka.schemas.template import TableStyleSpec, Typography

_NUM_RE = re.compile(r"^[\s\d.,%+\-–—×x/]+(\s?(млн|млрд|тыс|k|m|b|₽|\$|%|ч|дн|шт))?\s*$", re.I)


def _is_numeric(text: str) -> bool:
    t = text.strip()
    return bool(t) and bool(_NUM_RE.match(t)) and any(ch.isdigit() for ch in t)


def _column_is_numeric(rows: list[list[str]], j: int) -> bool:
    cells = [row[j] for row in rows if j < len(row) and row[j].strip()]
    return bool(cells) and all(_is_numeric(c) for c in cells)


def _set_borders(cell, color_hex: Optional[str], width_emu: int = 6350, bottom_only: bool = True) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        for old in tcPr.findall(q(tag)):
            tcPr.remove(old)
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        ln = etree.SubElement(tcPr, q(tag))
        if color_hex and (tag == "a:lnB" or not bottom_only):
            ln.set("w", str(width_emu))
            sf = etree.SubElement(ln, q("a:solidFill"))
            c = etree.SubElement(sf, q("a:srgbClr"))
            c.set("val", color_hex.upper())
        else:
            etree.SubElement(ln, q("a:noFill"))
    # lnX elements must precede fill elements inside tcPr: move them to the front
    for tag in reversed(("a:lnL", "a:lnR", "a:lnT", "a:lnB")):
        el = tcPr.find(q(tag))
        if el is not None:
            tcPr.remove(el)
            tcPr.insert(0, el)


def add_table(slide: Slide, bbox: Bbox, table: TableData, style: TableStyleSpec, typography: Typography, font_family: Optional[str] = None):
    n_rows = len(table.rows) + 1
    n_cols = len(table.columns)
    gf = slide.shapes.add_table(n_rows, n_cols, Emu(bbox.x), Emu(bbox.y), Emu(bbox.w), Emu(bbox.h))
    tbl = gf.table
    tblPr = tbl._tbl.tblPr
    tblPr.set("bandRow", "0")
    tblPr.set("firstRow", "1")
    style_id = tblPr.find(q("a:tableStyleId"))
    if style_id is not None:
        tblPr.remove(style_id)  # plain table: our own fills and borders only
    family = font_family or typography.primary_family
    size = style.font_size_pt or typography.size_for("small", 12.0)
    body = typography.size_for("body", size)
    if body > size and bbox.h / n_rows >= 2.8 * body * 12700:
        size = body  # a short table in a big area reads at body size, not at footnote size
    # rows as tall as their text needs (with air), never stretched over the whole area: a 2-row table is not a banner
    row_h = int(min(bbox.h / n_rows, size * 2.6 * 12700))
    for r in tbl.rows:
        r.height = Emu(row_h)
    gf.height = Emu(row_h * n_rows)
    # columns share the width by the length of their longest entry (labels get room, numbers stay compact)
    lengths = []
    for j in range(n_cols):
        texts = [table.columns[j]] + [row[j] for row in table.rows if j < len(row)]
        lengths.append(max((len(t) for t in texts), default=1))
    med = sorted(lengths)[len(lengths) // 2] or 1
    # a column is never narrower than its header word set in bold (+2 chars of padding)
    weights = [max(min(max(n, 0.6 * med), 3 * med), max((len(w) for w in table.columns[j].split()), default=1) * 1.1 + 2) for j, n in enumerate(lengths)]
    total = sum(weights) or 1
    widths = [int(bbox.w * w / total) for w in weights]
    widths[-1] += bbox.w - sum(widths)
    for c, w in zip(tbl.columns, widths):
        c.width = Emu(w)
    body_hex = style.body_text_hex or "000000"

    def write(cell, text: str, *, bold: bool, color_hex: str, align: PP_ALIGN, fill_hex: Optional[str]) -> None:
        cell.text = ""
        tf = cell.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = align
        run = p.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = RGBColor.from_string(color_hex.upper())
        if family:
            run.font.name = family
        cell.margin_left = cell.margin_right = Emu(72000)
        cell.margin_top = cell.margin_bottom = Emu(36000)
        if fill_hex:
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor.from_string(fill_hex.upper())
        else:
            cell.fill.background()

    header_fill = style.header_fill_hex
    header_text = style.header_text_hex or "FFFFFF"
    # one alignment per column, shared by the header and the body: numeric columns (every non-empty cell is a number) go right
    aligns = [PP_ALIGN.RIGHT if j > 0 and _column_is_numeric(table.rows, j) else PP_ALIGN.LEFT for j in range(n_cols)]
    for j, col in enumerate(table.columns):
        write(tbl.cell(0, j), col, bold=True, color_hex=header_text, align=aligns[j], fill_hex=header_fill)
        _set_borders(tbl.cell(0, j), None)
    for i, row in enumerate(table.rows, start=1):
        band = style.band_fill_hex if (n_rows > 5 and i % 2 == 0) else None
        for j in range(n_cols):
            text = row[j] if j < len(row) else ""
            write(tbl.cell(i, j), text, bold=False, color_hex=body_hex, align=aligns[j], fill_hex=band)
            _set_borders(tbl.cell(i, j), style.border_hex or "D9D9D9")
    return gf
