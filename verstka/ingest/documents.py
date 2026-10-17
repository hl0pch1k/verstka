"""A person's document (DOCX, PDF, Markdown, text, a web page) → its structure: headings, paragraphs, lists, tables.

Used by «Из файла» on the create screen (the text goes into the field as Markdown, the tables with figures become data
files of the second stage) and by the knowledge base (verstka/knowledge: every fragment knows its document, section,
page and paragraph — the source shown next to a fact on a slide).

- DOCX: read straight from the package (word/document.xml through lxml, no python-docx): the heading styles
  («Heading 1», «Заголовок 1», «Title», outline levels), numbered and bulleted lists, tables (merged cells filled),
  the title of the document's properties. Legacy .doc, .rtf and .odt are converted to DOCX by LibreOffice first.
- PDF: pypdf with a text visitor: every piece of text with its position and size → lines → headings by size and
  weight against the body size, paragraphs by line gaps, tables by aligned columns over 3+ lines; running headers,
  footers and page numbers repeated over the pages are dropped. A PDF without a text layer (a scan) is said in words:
  «скан без текстового слоя».
- HTML (a public page of the knowledge base): the article or main element when there is one, headings, paragraphs,
  list items and tables; scripts, menus, headers and footers out.

Errors are DocumentError with a message a person can act on (Russian: the UI shows it)."""

from __future__ import annotations

import io
import logging
import math
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Optional

log = logging.getLogger(__name__)

DOC_EXTS = (".docx", ".docm", ".dotx", ".pdf")
LEGACY_DOC_EXTS = (".doc", ".rtf", ".odt")
TEXT_EXTS = (".md", ".markdown", ".txt", ".text")
HTML_EXTS = (".html", ".htm")
ALL_EXTS = DOC_EXTS + LEGACY_DOC_EXTS + TEXT_EXTS + HTML_EXTS

MAX_XML_BYTES = 60 * 1024 * 1024  # word/document.xml unpacked: more is a zip bomb, not a document
MAX_PDF_PAGES = 400
MAX_TABLE_ROWS = 400
DATA_FIRST_PROSE = 600  # characters of text around the tables below which a document is its tables (data_first)

BlockKind = Literal["heading", "para", "item", "table"]


class DocumentError(ValueError):
    """A document that cannot be read — the message is for the person (Russian)."""


@dataclass
class DocTable:
    rows: list[list[str]]
    caption: Optional[str] = None

    @property
    def width(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def markdown(self) -> str:
        w = self.width
        if not self.rows or w == 0:
            return ""
        rows = [[_cell(c) for c in r] + [""] * (w - len(r)) for r in self.rows]
        out = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join(["---"] * w) + "|"]
        out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(out)

    def numeric_columns(self) -> int:
        """Columns (after the first) whose body cells are mostly numbers: a table of figures has at least one."""
        if len(self.rows) < 3:
            return 0
        body = self.rows[1:]
        n = 0
        for j in range(1, self.width):
            vals = [r[j] for r in body if j < len(r) and r[j].strip()]
            if len(vals) >= 2 and sum(1 for v in vals if is_number_cell(v)) >= 0.6 * len(vals):
                n += 1
        return n

    @property
    def is_data(self) -> bool:
        """A table for charts (its figures become a data file): 2+ body rows and a column of numbers."""
        return self.numeric_columns() >= 1


@dataclass
class Block:
    kind: BlockKind
    text: str = ""
    level: int = 0  # heading 1..6; list item depth 0..
    ordered: bool = False
    page: Optional[int] = None  # 1-based (PDF)
    num: Optional[int] = None  # an ordered item's own number as the document writes it («3.1», «5.» in a PDF)
    table: Optional[DocTable] = None


@dataclass
class DocumentText:
    name: str
    kind: str  # docx | pdf | md | txt | html
    title: str = ""
    blocks: list[Block] = field(default_factory=list)
    pages: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def tables(self) -> list[DocTable]:
        return [b.table for b in self.blocks if b.kind == "table" and b.table is not None]

    @property
    def data_tables(self) -> list[DocTable]:
        return [t for t in self.tables if t.is_data]

    @property
    def headings(self) -> int:
        return sum(1 for b in self.blocks if b.kind == "heading")

    def plain(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.kind != "table" and b.text)

    def markdown(self, data_tables: bool = True) -> str:
        """The document as Markdown: «#» headings (the first level the document uses becomes «#»), paragraphs, «-» and
        «1.» lists, «|» tables. `data_tables=False`: the tables of figures are left out (they go to the data panel as
        data files; the text keeps the tables of words)."""
        levels = sorted({b.level for b in self.blocks if b.kind == "heading"})
        shift = {lv: min(6, i + 1) for i, lv in enumerate(levels)}
        out: list[str] = []
        num: dict[int, int] = {}
        prev: Optional[str] = None
        for b in self.blocks:
            if b.kind == "item":
                if prev != "item":
                    num = {}
                    out.append("")
                depth = max(0, min(4, b.level))
                for d in [d for d in num if d > depth]:
                    del num[d]
                num[depth] = b.num if b.num is not None and b.num > num.get(depth, 0) else num.get(depth, 0) + 1
                mark = f"{num[depth]}." if b.ordered else "-"
                out.append("  " * depth + f"{mark} {b.text}")
            elif b.kind == "heading":
                out += ["", "#" * shift.get(b.level, 2) + " " + b.text]
            elif b.kind == "table" and b.table is not None:
                if not data_tables and b.table.is_data:
                    continue
                md = b.table.markdown()
                if md:
                    if b.table.caption and not _caption_above(out, b.table.caption):
                        out += ["", b.table.caption.rstrip(":") + ":"]
                    out += ["", md]
            elif b.text:
                out += ["", b.text]
            prev = b.kind
        text = "\n".join(out)
        return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"

    @property
    def prose_chars(self) -> int:
        """Characters of the text around the tables (headings, paragraphs, list items)."""
        return sum(len(b.text) for b in self.blocks if b.kind != "table")

    @property
    def data_first(self) -> bool:
        """The document is mostly its tables of figures (a short note around them): its tables go to the data panel as
        data files and its text is the brief. A document with text of its own keeps its tables inline: the deck is the
        whole document laid out, its tables shown as charts and tables where they stand."""
        if not self.data_tables:
            return False
        return self.prose_chars < DATA_FIRST_PROSE // 2 or (self.prose_chars < DATA_FIRST_PROSE and self.headings <= 2)

    def summary(self) -> dict:
        return {
            "name": self.name, "kind": self.kind, "title": self.title, "pages": self.pages, "headings": self.headings,
            "paragraphs": sum(1 for b in self.blocks if b.kind in ("para", "item")), "tables": len(self.tables),
            "data_tables": len(self.data_tables), "chars": sum(len(b.text) for b in self.blocks), "prose_chars": self.prose_chars,
            "data_first": self.data_first, "warnings": list(self.warnings),
        }


def _caption_above(out: list[str], caption: str) -> bool:
    last = next((ln for ln in reversed(out) if ln.strip()), "")
    return last.strip().lstrip("#").strip().rstrip(":").lower() == caption.strip().rstrip(":").lower()


def _cell(c: str) -> str:
    return " ".join((c or "").replace("|", "/").split())


_NUM_CELL_RE = re.compile(r"^[−\-–+]?\s*[\d\s  ]*\d(?:[.,]\d+)?\s*(?:%|‰|[₽$€]|руб\.?|тыс\.?|млн|млрд|шт\.?|чел\.?|п\.п\.?|pp|x|×)?$", re.I)


def is_number_cell(v: str) -> bool:
    s = (v or "").strip().replace(" ", " ")
    return bool(s) and bool(_NUM_CELL_RE.match(s)) and len(s) <= 24


# ------------------------------------------------------------------ entry point


def read_document(name: str, data: bytes) -> DocumentText:
    """The document's structure by its bytes (the name says the format when the bytes do not)."""
    ext = Path(name or "").suffix.lower()
    if not data:
        raise DocumentError(f"Файл «{name}» пустой")
    head = data[:8]
    if head.startswith(b"%PDF"):
        return read_pdf(name, data)
    if head.startswith(b"PK"):
        if ext in (".odt",):
            return read_docx(name, _convert_to_docx(name, data))
        return read_docx(name, data)
    if ext in (".doc", ".rtf") or head.startswith(b"\xd0\xcf\x11\xe0") or head.startswith(b"{\\rtf"):
        return read_docx(name, _convert_to_docx(name, data))
    if ext == ".pdf":
        raise DocumentError(f"«{name}» — не PDF: файл повреждён или это другой формат")
    if ext in (".docx", ".docm", ".dotx"):
        raise DocumentError(f"«{name}» — не документ Word: файл повреждён или это другой формат")
    text = decode_text(data)
    if ext in HTML_EXTS or re.match(r"\s*(?:<!doctype html|<html)", text[:400], re.I):
        return read_html(name, text)
    return read_markdown(name, text, kind="md" if ext in (".md", ".markdown") else "txt")


def decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _convert_to_docx(name: str, data: bytes) -> bytes:
    """.doc / .rtf / .odt → DOCX by LibreOffice (headless, its own profile)."""
    import os
    import subprocess
    import tempfile

    from verstka.ingest.render import find_soffice

    soffice = find_soffice()
    if not soffice:
        raise DocumentError(f"Чтобы открыть «{name}», на сервере нужен LibreOffice — сохраните документ как .docx или .pdf")
    ext = Path(name).suffix.lower() or ".doc"
    with tempfile.TemporaryDirectory(prefix="verstka_doc_", ignore_cleanup_errors=True) as tmp:
        src = Path(tmp) / f"source{ext}"
        src.write_bytes(data)
        out_dir = Path(tmp) / "out"
        profile = Path(tmp) / "profile"
        env = os.environ.copy()
        env["SAL_USE_VCLPLUGIN"] = "svp"
        cmd = [soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore", "--convert-to", "docx", "--outdir", str(out_dir), str(src)]
        try:
            subprocess.run(cmd, env=env, capture_output=True, timeout=90)
        except subprocess.TimeoutExpired as e:
            raise DocumentError(f"«{name}» слишком долго открывается — сохраните его как .docx или .pdf") from e
        out = out_dir / "source.docx"
        if not out.exists():
            raise DocumentError(f"Не получилось открыть «{name}» — сохраните его как .docx или .pdf")
        return out.read_bytes()


# ------------------------------------------------------------------ Markdown / text


_MD_HEAD_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_ITEM_RE = re.compile(r"^(\s*)(?:([-*•–—])|(\d{1,3})[.)])\s+(.+)$")


def read_markdown(name: str, text: str, kind: str = "md") -> DocumentText:
    doc = DocumentText(name=name, kind=kind)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            doc.blocks.append(Block("para", " ".join(" ".join(para).split())))
            para.clear()

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            flush()
            i += 1
            continue
        m = _MD_HEAD_RE.match(s)
        if m:
            flush()
            doc.blocks.append(Block("heading", m.group(2).strip(), level=len(m.group(1))))
            i += 1
            continue
        if s.startswith("|") and s.count("|") >= 2:
            flush()
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                r = lines[i].strip().strip("|")
                cells = [c.strip() for c in r.split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                cap = _caption_from(doc.blocks)
                doc.blocks.append(Block("table", table=DocTable(rows[:MAX_TABLE_ROWS], caption=cap)))
            continue
        m = _MD_ITEM_RE.match(ln)
        if m:
            flush()
            depth = len(m.group(1).replace("\t", "  ")) // 2
            doc.blocks.append(Block("item", m.group(4).strip(), level=depth, ordered=bool(m.group(3))))
            i += 1
            continue
        para.append(s)
        i += 1
    flush()
    # a plain text's first line, short and without an end stop, is its title («Команда и найм»)
    if kind == "txt" and doc.blocks and doc.blocks[0].kind == "para" and not any(b.kind == "heading" for b in doc.blocks):
        first_line = text.strip().split("\n", 1)[0].strip()
        if first_line and len(first_line) <= 90 and not first_line.endswith((".", ",", ";", ":")):
            rest = doc.blocks[0].text[len(first_line):].strip()
            doc.blocks[0:1] = [Block("heading", first_line, level=1)] + ([Block("para", rest)] if rest else [])
    first = next((b for b in doc.blocks if b.kind == "heading"), None)
    doc.title = first.text if first else Path(name).stem
    return doc


def _caption_from(blocks: list[Block]) -> Optional[str]:
    """The table's caption: the short paragraph right above it («Выручка по кварталам, млн ₽:», «Таблица 2. …»)."""
    if not blocks:
        return None
    b = blocks[-1]
    if b.kind == "para" and len(b.text) <= 140 and (b.text.rstrip().endswith(":") or re.match(r"^(?:таблица|табл\.)\s*\d*", b.text, re.I)):
        return b.text.rstrip().rstrip(":")
    return None


# ------------------------------------------------------------------ DOCX

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = "{%s}" % W
_HEAD_STYLE_RE = re.compile(r"^(?:heading|заголовок|überschrift|titre)\s*(\d)$", re.I)


def _xml(z: zipfile.ZipFile, part: str):
    from lxml import etree

    try:
        info = z.getinfo(part)
    except KeyError:
        return None
    if info.file_size > MAX_XML_BYTES:
        raise DocumentError("Документ слишком большой — оставьте в нём только нужные разделы")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_blank_text=False)
    try:
        return etree.fromstring(z.read(part), parser)
    except etree.XMLSyntaxError as e:
        raise DocumentError("Документ Word повреждён — откройте его и сохраните заново как .docx") from e


def _styles(z: zipfile.ZipFile) -> dict[str, tuple[Optional[int], bool]]:
    """styleId → (heading level or None, is a list style)."""
    root = _xml(z, "word/styles.xml")
    out: dict[str, tuple[Optional[int], bool]] = {}
    if root is None:
        return out
    based: dict[str, str] = {}
    for st in root.iter(_W + "style"):
        sid = st.get(_W + "styleId") or ""
        name_el = st.find(_W + "name")
        name = (name_el.get(_W + "val") if name_el is not None else "") or sid
        level: Optional[int] = None
        m = _HEAD_STYLE_RE.match(name.strip()) or _HEAD_STYLE_RE.match(sid.strip())
        if m:
            level = int(m.group(1))
        elif name.strip().lower() in ("title", "название", "заголовок"):
            level = 0
        else:
            ol = st.find(f"{_W}pPr/{_W}outlineLvl")
            if ol is not None and (ol.get(_W + "val") or "").isdigit() and int(ol.get(_W + "val")) < 9:
                level = int(ol.get(_W + "val")) + 1
        is_list = bool(re.search(r"list|списк", name, re.I))
        out[sid] = (level, is_list)
        b = st.find(_W + "basedOn")
        if b is not None:
            based[sid] = b.get(_W + "val") or ""
    for sid, (lv, li) in list(out.items()):
        seen = set()
        cur = sid
        while lv is None and cur in based and cur not in seen:
            seen.add(cur)
            cur = based[cur]
            lv = out.get(cur, (None, False))[0]
        out[sid] = (lv, li)
    return out


def _numbering(z: zipfile.ZipFile) -> dict[tuple[str, int], bool]:
    """(numId, ilvl) → ordered (a decimal / letter / roman numbering) or a bullet."""
    root = _xml(z, "word/numbering.xml")
    if root is None:
        return {}
    abstract: dict[str, dict[int, bool]] = {}
    for a in root.iter(_W + "abstractNum"):
        lv: dict[int, bool] = {}
        for l in a.iter(_W + "lvl"):
            fmt = l.find(_W + "numFmt")
            v = (fmt.get(_W + "val") if fmt is not None else "bullet") or "bullet"
            lv[int(l.get(_W + "ilvl") or 0)] = v not in ("bullet", "none")
        abstract[a.get(_W + "abstractNumId") or ""] = lv
    out: dict[tuple[str, int], bool] = {}
    for n in root.iter(_W + "num"):
        aid = n.find(_W + "abstractNumId")
        lv = abstract.get(aid.get(_W + "val") if aid is not None else "", {})
        for k, v in lv.items():
            out[(n.get(_W + "numId") or "", k)] = v
    return out


def _run_text(el) -> str:
    parts: list[str] = []
    for node in el.iter(_W + "t", _W + "tab", _W + "br", _W + "cr", _W + "noBreakHyphen", _W + "sym"):
        tag = node.tag
        if tag == _W + "t":
            parts.append(node.text or "")
        elif tag == _W + "tab":
            parts.append(" ")
        elif tag in (_W + "br", _W + "cr"):
            parts.append(" ")
        elif tag == _W + "noBreakHyphen":
            parts.append("-")
    return " ".join("".join(parts).split())


def _para_text(p) -> str:
    # a paragraph's own runs (a text box inside it is a drawing: its paragraphs come as their own)
    parts: list[str] = []
    for child in p:
        if child.tag in (_W + "r", _W + "hyperlink", _W + "ins", _W + "smartTag", _W + "fldSimple", _W + "sdt"):
            if child.find(f".//{_W}txbxContent") is not None:
                continue
            parts.append(_run_text(child))
    return " ".join(" ".join(parts).split())


def _all_bold(p) -> bool:
    runs = [r for r in p.iter(_W + "r") if (_run_text(r) or "").strip()]
    if not runs:
        return False
    for r in runs:
        b = r.find(f"{_W}rPr/{_W}b")
        if b is None or (b.get(_W + "val") or "true") in ("0", "false"):
            return False
    return True


def read_docx(name: str, data: bytes) -> DocumentText:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise DocumentError(f"«{name}» — не документ Word: файл повреждён или это другой формат") from e
    with z:
        if "word/document.xml" not in z.namelist():
            raise DocumentError(f"«{name}» — не документ Word: внутри нет текста документа")
        if sum(i.file_size for i in z.infolist()) > 400 * 1024 * 1024:
            raise DocumentError("Документ слишком большой — оставьте в нём только нужные разделы")
        styles = _styles(z)
        numbering = _numbering(z)
        root = _xml(z, "word/document.xml")
        title = ""
        core = _xml(z, "docProps/core.xml")
        if core is not None:
            t = core.find("{http://purl.org/dc/elements/1.1/}title")
            title = " ".join((t.text or "").split()) if t is not None else ""
    doc = DocumentText(name=name, kind="docx")
    body = root.find(_W + "body")
    if body is None:
        raise DocumentError(f"В «{name}» нет текста")

    def walk(container) -> Iterable:
        for el in container:
            if el.tag == _W + "sdt":
                content = el.find(_W + "sdtContent")
                if content is not None:
                    yield from walk(content)
            elif el.tag in (_W + "p", _W + "tbl"):
                yield el

    for el in walk(body):
        if el.tag == _W + "tbl":
            t = _docx_table(el)
            if t is not None:
                t.caption = _caption_from(doc.blocks)
                doc.blocks.append(Block("table", table=t))
            else:
                # a one-cell «table» is a framed paragraph (a note, a quote): its text as paragraphs
                for para in el.iter(_W + "p"):
                    tx = _para_text(para)
                    if tx:
                        doc.blocks.append(Block("para", tx))
            continue
        text = _para_text(el)
        if not text:
            continue
        ppr = el.find(_W + "pPr")
        sid = ""
        level: Optional[int] = None
        if ppr is not None:
            ps = ppr.find(_W + "pStyle")
            sid = ps.get(_W + "val") if ps is not None else ""
            ol = ppr.find(_W + "outlineLvl")
            if ol is not None and (ol.get(_W + "val") or "").isdigit() and int(ol.get(_W + "val")) < 9:
                level = int(ol.get(_W + "val")) + 1
        st_level, st_list = styles.get(sid, (None, False))
        level = level if level is not None else st_level
        num = ppr.find(_W + "numPr") if ppr is not None else None
        if level is not None and len(text) <= 200:
            doc.blocks.append(Block("heading", text, level=max(0, level)))
            if level == 0 and not title:
                title = text
            continue
        if num is not None or st_list:
            ilvl_el = num.find(_W + "ilvl") if num is not None else None
            nid_el = num.find(_W + "numId") if num is not None else None
            ilvl = int(ilvl_el.get(_W + "val") or 0) if ilvl_el is not None else 0
            nid = nid_el.get(_W + "val") if nid_el is not None else ""
            if nid != "0":
                doc.blocks.append(Block("item", text, level=ilvl, ordered=numbering.get((nid or "", ilvl), False)))
                continue
        # a short paragraph all in bold with no end stop is a heading the author made by hand
        if len(text) <= 90 and not text.rstrip().endswith((".", ",", ";", ":")) and _all_bold(el):
            doc.blocks.append(Block("heading", text, level=7))
            continue
        doc.blocks.append(Block("para", text))
    first = next((b.text for b in doc.blocks if b.kind == "heading"), "")
    doc.title = title or first or Path(name).stem
    if not any(b.text or b.table for b in doc.blocks):
        raise DocumentError(f"В «{name}» нет текста")
    return doc


def _docx_table(tbl) -> Optional[DocTable]:
    rows: list[list[str]] = []
    vmerge_above: dict[int, str] = {}
    for tr in tbl.findall(_W + "tr"):
        row: list[str] = []
        col = 0
        for tc in tr.findall(_W + "tc"):
            tcpr = tc.find(_W + "tcPr")
            span = 1
            vm = None
            if tcpr is not None:
                gs = tcpr.find(_W + "gridSpan")
                if gs is not None and (gs.get(_W + "val") or "").isdigit():
                    span = max(1, min(30, int(gs.get(_W + "val"))))
                vme = tcpr.find(_W + "vMerge")
                if vme is not None:
                    vm = vme.get(_W + "val") or "continue"
            text = " ".join(_para_text(p) for p in tc.iter(_W + "p"))
            text = " ".join(text.split())
            if vm == "continue":
                text = vmerge_above.get(col, text)
            for k in range(span):
                row.append(text if k == 0 else "")
                vmerge_above[col + k] = text
            col += span
        if any(c.strip() for c in row):
            rows.append(row)
        if len(rows) >= MAX_TABLE_ROWS:
            break
    if not rows:
        return None
    # a one-cell «table» is a framed paragraph
    if len(rows) == 1 and sum(1 for c in rows[0] if c.strip()) <= 1:
        return None
    w = max(len(r) for r in rows)
    return DocTable([r + [""] * (w - len(r)) for r in rows])


# ------------------------------------------------------------------ PDF


@dataclass
class _Piece:
    x: float
    y: float
    size: float
    text: str
    bold: bool
    width: float


@dataclass
class _Line:
    page: int
    y: float
    size: float
    bold: bool
    cells: list[tuple[float, float, str]]  # (x start, x end, text)

    @property
    def text(self) -> str:
        return " ".join(" ".join(c[2] for c in self.cells).split())

    @property
    def x0(self) -> float:
        return self.cells[0][0] if self.cells else 0.0

    @property
    def x1(self) -> float:
        return self.cells[-1][1] if self.cells else 0.0


def _mult(m: list[float], n: list[float]) -> list[float]:
    return [
        m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3],
        m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3],
        m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5],
    ]


def _font_bold(font: Optional[dict]) -> bool:
    try:
        base = str((font or {}).get("/BaseFont") or "")
    except Exception:  # noqa: BLE001
        return False
    return bool(re.search(r"bold|black|heavy|semibold|demi", base, re.I))


def _page_pieces(page, plain: Optional[list] = None) -> list[_Piece]:
    """The page's pieces of text with their position, size and weight; `plain` gets pypdf's own text of the page (its
    spacing is right where a run's words come at one position: the words' gaps are in the run's offsets)."""
    pieces: list[_Piece] = []

    def visit(text, cm, tm, font, size) -> None:
        if not text or not text.strip():
            return
        try:
            m = _mult(list(tm), list(cm))
        except Exception:  # noqa: BLE001
            return
        scale = math.hypot(m[2], m[3]) or 1.0
        eff = float(size or 0) * scale if size else scale
        if eff <= 0.5:
            eff = float(size or 10)
        for k, part in enumerate(text.split("\n")):
            if part.strip():
                pieces.append(_Piece(m[4], m[5] - k * eff * 1.2, eff, part, _font_bold(font), 0.5 * eff * len(part)))

    text = page.extract_text(visitor_text=visit)
    if plain is not None:
        plain.append(text or "")
    return pieces


def _lines_of(pieces: list[_Piece], page_no: int) -> list[_Line]:
    if not pieces:
        return []
    pieces = sorted(pieces, key=lambda p: (-round(p.y, 1), p.x))
    groups: list[list[_Piece]] = []
    for p in pieces:
        g = next((g for g in groups[-3:] if abs(g[0].y - p.y) <= 0.45 * max(g[0].size, p.size)), None)
        if g is None:
            groups.append([p])
        else:
            g.append(p)
    out: list[_Line] = []
    for g in groups:
        g.sort(key=lambda p: p.x)
        size = max(p.size for p in g)
        cells: list[tuple[float, float, str]] = []
        prev_x: Optional[float] = None
        for p in g:
            if cells and prev_x is not None and abs(p.x - prev_x) < 0.5:
                # a run's words all at the run's start (their gaps are in its offsets): one cell, spaced by the page text
                x0, x1, t = cells[-1]
                glue = "" if (t.endswith(" ") or p.text[:1] in ",.:;!?)»") else " "
                cells[-1] = (x0, x1 + p.width, t + glue + p.text)
                continue
            prev_x = p.x
            inside = next((k for k, c in enumerate(cells) if c[0] <= p.x < c[1] - 0.3 * size and "  " in c[2]), None)
            if inside is not None:
                # a glyph drawn on its own over the gap left for it in a run («412 млн  — …» + «₽»): into that gap
                x0, x1, t = cells[inside]
                at = (p.x - x0) / max(1e-6, x1 - x0) * len(t)
                gaps = [m.start() + 1 for m in re.finditer(r"  ", t)]
                g_at = min(gaps, key=lambda q: abs(q - at))
                cells[inside] = (x0, x1, t[:g_at] + p.text.strip() + t[g_at:])
                continue
            if cells and p.x - cells[-1][1] <= 1.6 * size:
                x0, _, t = cells[-1]
                sep = "" if (t.endswith(("-", " ")) or p.text.startswith(" ") or p.x - cells[-1][1] < 0.12 * size) else " "
                cells[-1] = (x0, max(cells[-1][1], p.x + p.width), t + sep + p.text)
            else:
                cells.append((p.x, p.x + p.width, p.text))
        cells = [(a, b, " ".join(t.split())) for a, b, t in cells if t.strip()]
        # a list's marker set apart from its text («•», «1.») is one cell with it
        if len(cells) >= 2 and _MARK_RE.fullmatch(cells[0][2]):
            cells = [(cells[0][0], cells[1][1], f"{cells[0][2]} {cells[1][2]}")] + cells[2:]
        if cells:
            out.append(_Line(page_no, g[0].y, size, all(p.bold for p in g), cells))
    out.sort(key=lambda ln: -ln.y)
    return out


_MARK_RE = re.compile(r"[•●▪◦‣∙·–—\-*]|\d{1,2}[.)]")
_PAGE_NO_RE = re.compile(r"^(?:стр\.?|страница|page|с\.)?\s*\d{1,4}(?:\s*(?:из|/|of)\s*\d{1,4})?$", re.I)
_BULLET_RE = re.compile(r"^(?:[•●▪◦‣∙·–—\-*]|\d{1,2}[.)])\s+")


def read_pdf(name: str, data: bytes) -> DocumentText:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as e:  # pragma: no cover - a dependency of the project
        raise DocumentError("На сервере нет чтения PDF (pypdf)") from e
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    raise DocumentError(f"«{name}» защищён паролем — снимите защиту и загрузите снова")
            except DocumentError:
                raise
            except Exception as e:  # noqa: BLE001
                raise DocumentError(f"«{name}» защищён паролем — снимите защиту и загрузите снова") from e
        pages = list(reader.pages)
    except DocumentError:
        raise
    except (PdfReadError, Exception) as e:  # noqa: BLE001
        raise DocumentError(f"«{name}» не читается как PDF — файл повреждён") from e
    doc = DocumentText(name=name, kind="pdf", pages=len(pages))
    if len(pages) > MAX_PDF_PAGES:
        doc.warnings.append(f"прочитаны первые {MAX_PDF_PAGES} страниц из {len(pages)}")
        pages = pages[:MAX_PDF_PAGES]
    lines: list[_Line] = []
    images = 0
    for k, page in enumerate(pages, 1):
        try:
            plain: list[str] = []
            got = _lines_of(_page_pieces(page, plain), k)
            _respace(got, plain[0] if plain else "")
            lines += got
        except Exception:  # noqa: BLE001 - a broken page: the others still count
            log.info("pdf page %d of %s not read", k, name, exc_info=True)
            doc.warnings.append(f"страница {k} не прочитана")
        try:
            res = page.get("/Resources") or {}
            xo = res.get("/XObject") if hasattr(res, "get") else None
            images += len(xo) if xo is not None else 0
        except Exception:  # noqa: BLE001
            pass
    chars = sum(len(ln.text) for ln in lines)
    if chars < 40 * max(1, len(pages)) * 0.25 and chars < 200:
        if images:
            raise DocumentError(f"«{name}» — скан без текстового слоя: текст в нём картинкой. Распознайте его (OCR) или загрузите исходный документ")
        raise DocumentError(f"В «{name}» нет текста")
    lines = _drop_running(lines, len(pages))
    _pdf_blocks(doc, lines)
    try:
        meta_title = (reader.metadata or {}).get("/Title") if reader.metadata else None
    except Exception:  # noqa: BLE001
        meta_title = None
    first = next((b.text for b in doc.blocks if b.kind == "heading"), "")
    mt = " ".join(str(meta_title or "").split())
    doc.title = first or (mt if mt and not re.search(r"\.(docx?|pdf|pptx?)$|^untitled|^microsoft", mt, re.I) else "") or Path(name).stem
    return doc


def _respace(lines: list[_Line], plain: str) -> None:
    """Each cell's text as the page's own text spells it (pypdf knows the glyphs' widths: «Каждую неделю», not
    «Каждуюнеделю»), found by its letters in order; a cell not found keeps its text."""
    if not plain or not lines:
        return
    keep = [i for i, ch in enumerate(plain) if not ch.isspace()]
    compact = "".join(plain[i] for i in keep)
    cursor = 0
    for ln in lines:
        new_cells = []
        for x0, x1, t in ln.cells:
            ct = "".join(t.split())
            if len(ct) < 2:
                new_cells.append((x0, x1, t))
                continue
            at = compact.find(ct, cursor)
            if at < 0 or at - cursor > 4000:
                at = compact.find(ct)
            if at < 0:
                new_cells.append((x0, x1, t))
                continue
            a, b = keep[at], keep[at + len(ct) - 1]
            spaced = " ".join(plain[a:b + 1].split())
            new_cells.append((x0, x1, spaced))
            cursor = at + len(ct)
        # a currency sign drawn from another font after the stop that follows it («млн :₽» → «млн ₽:»)
        ln.cells = [(a, b, _SIGN_AFTER_STOP_RE.sub(r" \2\1", t)) for a, b, t in new_cells]


_SIGN_AFTER_STOP_RE = re.compile(r"\s([:;,.])([₽$€£¥])(?=\s|$)")


def _norm_running(t: str) -> str:
    return re.sub(r"\d+", "#", t.lower()).strip()


def _drop_running(lines: list[_Line], n_pages: int) -> list[_Line]:
    """Running headers and footers (the same line on most pages) and bare page numbers out."""
    if n_pages >= 3:
        per = Counter()
        for p in range(1, n_pages + 1):
            for t in {_norm_running(ln.text) for ln in lines if ln.page == p}:
                per[t] += 1
        running = {t for t, c in per.items() if c >= max(3, 0.6 * n_pages) and len(t) <= 120}
    else:
        running = set()
    return [ln for ln in lines if not _PAGE_NO_RE.match(ln.text.strip()) and _norm_running(ln.text) not in running]


def _body_size(lines: list[_Line]) -> float:
    c: Counter = Counter()
    for ln in lines:
        c[round(ln.size * 2) / 2] += len(ln.text)
    return c.most_common(1)[0][0] if c else 10.0


def _table_runs(lines: list[_Line]) -> list[tuple[int, int]]:
    """Runs of lines (start, end) that are a table: 3+ consecutive lines of 2+ cells whose cells start at the same
    columns (a body line wrapped inside a cell — one cell — may sit between them)."""
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(lines):
        if len(lines[i].cells) < 2:
            i += 1
            continue
        j = i
        cols = [c[0] for c in lines[i].cells]
        multi = 0
        while j < len(lines) and lines[j].page == lines[i].page:
            ln = lines[j]
            if len(ln.cells) >= 2:
                if not _aligned(cols, [c[0] for c in ln.cells], ln.size):
                    break
                multi += 1
            elif multi and _wrapped_cell(lines[j - 1], ln) and j + 1 < len(lines) and len(lines[j + 1].cells) >= 2 and lines[j + 1].page == ln.page:
                pass  # a wrapped cell between two rows
            else:
                break
            j += 1
        if multi >= 3:
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _wrapped_cell(prev: _Line, ln: _Line) -> bool:
    """A one-cell line right under a table row that goes on with one of its cells: the same size and weight, the
    row pitch apart (a heading between two tables is bigger, bolder or further down)."""
    return abs(prev.size - ln.size) <= 0.3 and ln.bold == prev.bold and prev.page == ln.page and 0 < prev.y - ln.y <= 1.45 * ln.size


def _aligned(cols: list[float], xs: list[float], size: float) -> bool:
    tol = 1.2 * size
    hits = sum(1 for x in xs if any(abs(x - c) <= tol for c in cols))
    return hits >= max(2, len(xs) - 1)


def _pdf_table(lines: list[_Line]) -> DocTable:
    starts: list[float] = []
    for ln in lines:
        for c in ln.cells:
            if not any(abs(c[0] - s) <= 1.2 * ln.size for s in starts):
                starts.append(c[0])
    starts.sort()
    rows: list[list[str]] = []
    for ln in lines:
        if len(ln.cells) < 2 and rows and len(lines) > 1:
            # a wrapped cell: its text goes to the cell of the row above at its column
            j = _col_of(starts, ln.cells[0][0], ln.size)
            rows[-1][j] = (rows[-1][j] + " " + ln.cells[0][2]).strip()
            continue
        row = [""] * len(starts)
        for c in ln.cells:
            j = _col_of(starts, c[0], ln.size)
            row[j] = (row[j] + " " + c[2]).strip()
        rows.append(row)
    keep = [j for j in range(len(starts)) if any(r[j] for r in rows)]
    return DocTable([[r[j] for j in keep] for r in rows][:MAX_TABLE_ROWS])


def _col_of(starts: list[float], x: float, size: float) -> int:
    best = min(range(len(starts)), key=lambda j: abs(starts[j] - x))
    return best


def _pdf_blocks(doc: DocumentText, lines: list[_Line]) -> None:
    body = _body_size(lines)
    runs = _table_runs(lines)
    in_table = {k: r for r in runs for k in range(r[0], r[1])}
    left = Counter(round(ln.x0) for ln in lines if ln.size <= body * 1.05)
    margin = left.most_common(1)[0][0] if left else 0
    widest = max((ln.x1 - ln.x0 for ln in lines), default=1.0) or 1.0
    head_sizes = sorted({round(ln.size * 2) / 2 for ln in lines if ln.size >= body * 1.15 and len(ln.text) <= 140}, reverse=True)
    para: list[_Line] = []

    def flush() -> None:
        if para:
            doc.blocks.append(Block("para", _join_lines([p.text for p in para]), page=para[0].page))
            para.clear()

    k = 0
    while k < len(lines):
        ln = lines[k]
        if k in in_table:
            a, b = in_table[k]
            flush()
            t = _pdf_table(lines[a:b])
            t.caption = _caption_from(doc.blocks)
            doc.blocks.append(Block("table", page=ln.page, table=t))
            k = b
            continue
        text = ln.text
        big = ln.size >= body * 1.15
        heading = (big or (ln.bold and ln.size >= body * 0.98)) and len(text) <= 140 and not text.rstrip().endswith((",", ";")) and not _BULLET_RE.match(text)
        if heading and ln.bold and not big and text.rstrip().endswith(".") and len(text) > 60:
            heading = False
        if heading:
            flush()
            rs = round(ln.size * 2) / 2
            level = min(5, head_sizes.index(rs) + 1) if big and rs in head_sizes else len(head_sizes) + 1
            prev = doc.blocks[-1] if doc.blocks else None
            # a heading over two lines: the same size, right below
            if prev is not None and prev.kind == "heading" and prev.level == level and prev.page == ln.page and k > 0 and \
                    lines[k - 1].size == ln.size and abs(lines[k - 1].y - ln.y) <= 1.7 * ln.size and len(prev.text) + len(text) <= 160:
                prev.text = f"{prev.text} {text}"
            else:
                doc.blocks.append(Block("heading", text, level=level, page=ln.page))
            k += 1
            continue
        m = _BULLET_RE.match(text)
        if m:
            flush()
            ordered = bool(re.match(r"\d", m.group(0)))
            num = int(re.match(r"\d+", m.group(0)).group(0)) if ordered else None
            item = text[m.end():].strip()
            # the item goes on in the lines below: those that start further right (its hanging indent), or a line that
            # goes on its unfinished sentence (no stop at the end, a lowercase start)
            j = k + 1
            while j < len(lines) and j not in in_table and lines[j].page == ln.page and not _BULLET_RE.match(lines[j].text) \
                    and abs(lines[j - 1].y - lines[j].y) <= 1.8 * lines[j].size and lines[j].size < body * 1.15 \
                    and (lines[j].x0 > ln.x0 + 0.5 * ln.size or (not item.rstrip().endswith((".", "!", "?", ":", ";")) and lines[j].text[:1].islower())):
                item = _join_lines([item, lines[j].text])
                j += 1
            doc.blocks.append(Block("item", item, level=0 if ln.x0 <= margin + 2 * ln.size else 1, ordered=ordered, page=ln.page, num=num))
            k = j
            continue
        if para:
            prev_ln = para[-1]
            gap = prev_ln.y - ln.y if prev_ln.page == ln.page else 99
            short_end = (prev_ln.x1 - prev_ln.x0) < 0.75 * widest and prev_ln.text.rstrip().endswith((".", "!", "?", ":", "»"))
            if gap > 1.75 * ln.size or short_end or abs(prev_ln.size - ln.size) > 0.6 or ln.x0 > prev_ln.x0 + 1.5 * ln.size:
                flush()
        para.append(ln)
        k += 1
    flush()


def _join_lines(parts: list[str]) -> str:
    out = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if out.endswith("-") and len(out) > 1 and out[-2].isalpha() and p[:1].islower():
            out = out[:-1] + p  # a word hyphenated at the line's end
        else:
            out = f"{out} {p}" if out else p
    return " ".join(out.split())


# ------------------------------------------------------------------ the tables of figures as data files


def data_tables_text(doc: DocumentText) -> str:
    """The document's tables of figures as a text the data reader takes (verstka/data/readers.py: a table in a text,
    its caption above it as «Название, единица:»), "" when there are none."""
    found = doc.data_tables
    parts = []
    for k, t in enumerate(found, 1):
        cap = (t.caption or "").strip().rstrip(":") or (f"Таблица {k}" if len(found) > 1 else "")
        parts.append((f"{cap}:\n" if cap else "") + t.markdown())
    return "\n\n".join(parts)


def document_tables(name: str, data: bytes) -> list:
    """The tables of figures of a DOCX / PDF document as data tables (schemas.data.Table, file = the document's name);
    DocumentError when the document is not read or has none (DataReadError of the reader passes)."""
    from verstka.data.readers import read_bytes

    doc = read_document(name, data)
    text = data_tables_text(doc)
    if not text:
        raise DocumentError("В документе нет таблиц с цифрами — его текст можно взять в поле «О чём презентация»")
    tables = read_bytes(f"{Path(name).stem or 'документ'}.md", text.encode("utf-8"))
    return [t.model_copy(update={"file": name}) for t in tables]


# ------------------------------------------------------------------ HTML

_DROP_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "iframe", "button", "template", "select")


def read_html(name: str, html: str) -> DocumentText:
    from lxml import html as lh

    doc = DocumentText(name=name, kind="html")
    try:
        root = lh.document_fromstring(html)
    except Exception as e:  # noqa: BLE001
        raise DocumentError("Страница не читается — это не HTML") from e
    title_el = root.find(".//title")
    page_title = " ".join((title_el.text_content() if title_el is not None else "").split())
    for bad in root.xpath("|".join(f"//{t}" for t in _DROP_TAGS)):
        bad.drop_tree()
    for bad in root.xpath("//*[@role='navigation' or @role='banner' or @role='contentinfo' or @aria-hidden='true']"):
        bad.drop_tree()
    main = root.xpath("//article") or root.xpath("//main") or root.xpath("//*[@role='main']") or root.xpath("//body") or [root]
    scope = max(main, key=lambda e: len(e.text_content() or ""))

    def text_of(el) -> str:
        return " ".join((el.text_content() or "").split())

    for el in scope.iter("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "blockquote", "dd", "pre"):
        if el.getparent() is None:
            continue
        if any(a.tag in ("table", "li", "p", "blockquote") for a in el.iterancestors()) and el.tag != "table":
            if el.tag == "p" and any(a.tag in ("li", "blockquote") for a in el.iterancestors()) and not any(a.tag == "table" for a in el.iterancestors()):
                pass
            else:
                continue
        if el.tag == "table":
            if any(a.tag == "table" for a in el.iterancestors()):
                continue
            rows = []
            for tr in el.iter("tr"):
                cells = [text_of(c) for c in tr if c.tag in ("td", "th")]
                if any(cells):
                    rows.append(cells)
            if rows:
                w = max(len(r) for r in rows)
                if w >= 2:
                    cap = el.find("caption")
                    t = DocTable([r + [""] * (w - len(r)) for r in rows][:MAX_TABLE_ROWS], caption=text_of(cap) if cap is not None else _caption_from(doc.blocks))
                    doc.blocks.append(Block("table", table=t))
            continue
        t = text_of(el)
        if not t:
            continue
        if el.tag[0] == "h" and el.tag[1:].isdigit():
            doc.blocks.append(Block("heading", t[:200], level=int(el.tag[1:])))
        elif el.tag == "li":
            if any(c.tag in ("ul", "ol") for c in el.iterdescendants()):
                t = " ".join((el.text or "").split()) or t
            parent = el.getparent()
            depth = sum(1 for a in el.iterancestors() if a.tag in ("ul", "ol")) - 1
            doc.blocks.append(Block("item", t, level=max(0, depth), ordered=parent is not None and parent.tag == "ol"))
        else:
            if len(t) >= 2:
                doc.blocks.append(Block("para", t))
    h1 = next((b.text for b in doc.blocks if b.kind == "heading" and b.level == 1), "")
    # «Облачные вычисления — Википедия», «Отчёт | Компания»: the page's own name without the site's
    doc.title = h1 or re.sub(r"\s+[—|–-]\s+[^—|–-]{2,40}$", "", page_title) or page_title or name
    if not doc.blocks:
        raise DocumentError("На странице нет текста — возможно, она собирается скриптом или закрыта входом")
    return doc


__all__ = [
    "ALL_EXTS", "Block", "DOC_EXTS", "DocTable", "DocumentError", "DocumentText", "LEGACY_DOC_EXTS", "data_tables_text", "decode_text", "document_tables",
    "is_number_cell", "read_docx", "read_document", "read_html", "read_markdown", "read_pdf",
]
