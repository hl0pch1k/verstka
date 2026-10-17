"""Render PPTX slides to JPEG via LibreOffice (PPTX → PDF) and poppler (PDF → images)."""

from __future__ import annotations

import html
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_MAC_SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
_FONT_DIR = Path(__file__).resolve().parents[1] / "fonts"  # Play (OFL): the font of the VK templates


def _fontconfig(profile: Path) -> Optional[str]:
    """Linux: a fontconfig file that adds the bundled fonts to the system ones, so previews and PDFs of VK decks are
    set in Play even where it is not installed (PowerPoint uses the font embedded in the deck; LibreOffice does not).
    macOS builds of LibreOffice read installed fonts only."""
    if not sys.platform.startswith("linux") or not _FONT_DIR.is_dir():
        return None
    conf = profile / "fonts.conf"
    conf.write_text(
        '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n'
        '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
        f"  <dir>{_FONT_DIR}</dir>\n</fontconfig>\n",
        encoding="utf-8",
    )
    return str(conf)


_warned_fonts = False


def _warn_missing_mac_fonts() -> None:
    """macOS: LibreOffice cannot be pointed at the bundled fonts — without Play installed, previews of the VK decks are
    set in a fallback (Arial Black for bold: wider figures, other line breaks). Say so once, with the fix."""
    global _warned_fonts
    if _warned_fonts or sys.platform != "darwin" or not _FONT_DIR.is_dir():
        return
    _warned_fonts = True
    dirs = [Path.home() / "Library/Fonts", Path("/Library/Fonts")]
    installed = {p.name.lower() for d in dirs if d.is_dir() for p in d.iterdir()}
    missing = [f.name for f in sorted(_FONT_DIR.glob("*.ttf")) if f.name.lower() not in installed]
    if missing:
        log.warning("шрифты %s не установлены: превью и PDF LibreOffice наберёт запасным шрифтом; установите: cp %s/*.ttf ~/Library/Fonts/", ", ".join(missing), _FONT_DIR)


_LATIN_FACE_RE = re.compile(rb"<a:latin\b[^>]*?\btypeface=\"([^\"]+)\"")


def _bundled_families() -> set[str]:
    """Families of the fonts shipped in verstka/fonts (Play): the Linux fontconfig file adds them for LibreOffice."""
    return {f.stem.split("-")[0].lower() for f in _FONT_DIR.glob("*.[ot]tf")} if _FONT_DIR.is_dir() else set()


def _deck_families(pptx: Path) -> set[str]:
    """Every family an `a:latin` names in the package (slides, layouts, masters, theme, charts); empty when the file
    is not a readable package."""
    families: set[str] = set()
    try:
        with zipfile.ZipFile(pptx) as z:
            for name in z.namelist():
                if name.startswith("ppt/") and name.endswith(".xml"):
                    for m in _LATIN_FACE_RE.finditer(z.read(name)):
                        families.add(html.unescape(m.group(1).decode("utf-8", "replace")).strip())
    except (zipfile.BadZipFile, OSError, KeyError):
        return set()
    return families


def font_replacements(pptx: Path, available: frozenset[str] | set[str] = frozenset()) -> dict[str, str]:
    """{family: stand-in} for every Latin/Cyrillic family the deck names (slides, layouts, masters, theme, charts)
    that this machine does not have — the table LibreOffice gets so that each run is set in one face of the family's
    class instead of a glyph-by-glyph fallback («Open Sans» → OpenSymbol digits + Helvetica letters + STIX «₽»).
    `available`: lower-case families LibreOffice will find anyway (the bundled Play on Linux)."""
    from verstka.rendering.fonts import render_standin  # lazy: keeps ingest importable without the rendering package

    families = _deck_families(pptx)
    out: dict[str, str] = {}
    for fam in sorted(families):
        if not fam or fam.lower() in available:
            continue
        try:
            sub = render_standin(fam)
        except Exception:  # noqa: BLE001 — a font probe never fails a render
            sub = None
        if sub and sub.lower() != fam.lower():
            out[fam] = sub
    return out


_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_CYRILLIC_RE = re.compile("[Ѐ-ӿ]")
_RPR_AFTER_LATIN = {"ea", "cs", "sym", "hlinkClick", "hlinkMouseOver", "rtl", "extLst"}
_CHART_PART_RE = re.compile(r"^ppt/charts/chart\d+\.xml$")
_SLIDE_PART_RE = re.compile(r"^ppt/slides/slide\d+\.xml$")


def _set_run_face(run, family: str, bold: bool) -> None:
    """`run` (a:r / a:fld) set in `family` (and bold): its own a:latin, created in schema order when inherited."""
    from lxml import etree

    rpr = run.find(f"{{{_A_NS}}}rPr")
    if rpr is None:
        rpr = etree.Element(f"{{{_A_NS}}}rPr")
        run.insert(0, rpr)
    latin = rpr.find(f"{{{_A_NS}}}latin")
    if latin is None:
        latin = etree.Element(f"{{{_A_NS}}}latin")
        anchor = next((c for c in rpr if isinstance(c.tag, str) and etree.QName(c).localname in _RPR_AFTER_LATIN), None)
        if anchor is not None:
            anchor.addprevious(latin)
        else:
            rpr.append(latin)
    latin.set("typeface", family)
    for attr in ("panose", "pitchFamily", "charset"):
        latin.attrib.pop(attr, None)
    if bold:
        rpr.set("b", "1")


def _split_glyph(run, ch: str, family: str, bold: bool) -> bool:
    """Every `ch` of `run` (an a:r) moved into a run of its own set in `family` (and bold); the rest keeps the run's
    properties. False when the run holds no `ch`."""
    import copy

    t_el = run.find(f"{{{_A_NS}}}t")
    text = t_el.text if t_el is not None and t_el.text else ""
    if ch not in text or run.getparent() is None:
        return False
    pieces = [x for x in re.split(f"({re.escape(ch)}+)", text) if x]
    anchor = run
    for i, piece in enumerate(pieces):
        new = run if i == 0 else copy.deepcopy(run)
        if i:
            anchor.addnext(new)
            anchor = new
        new.find(f"{{{_A_NS}}}t").text = piece
        if piece[0] == ch:
            _set_run_face(new, family, bold)
    return True


def run_faces(pptx: Path) -> dict[str, bytes]:
    """{slide or chart part: its XML for LibreOffice}, so that LibreOffice draws each run in one face:

    - every run holding Cyrillic whose family this machine has but whose face lacks Cyrillic (see
      rendering.fonts.cyrillic_standin) is set in the stand-in — not Latin letters and digits in the family +
      Cyrillic letters in a fallback. Runs without Cyrillic (the template's Latin chrome) keep their family; a heavy
      face name («Avenir Heavy») keeps its weight as bold;
    - every «₽» of a run whose face (after the stand-ins) lacks it gets a run of its own in a face of the same class
      that has it (rendering.fonts.glyph_standin) — not a thin serif «₽» from STIX Two Math beside sans digits; a
      chart's data labels / value axis whose number format holds «₽» are set in that face as a whole.

    Empty when there is nothing to change (the dataset templates: Play has Cyrillic and «₽»)."""
    from verstka.rendering.fonts import (  # lazy, as in font_replacements
        cyrillic_standin,
        glyph_standin,
        is_heavy_face_name,
        is_installed,
        render_standin,
    )

    families = _deck_families(pptx)
    need_cyr = any(cyrillic_standin(f, False) or cyrillic_standin(f, True) for f in families if f)
    try:
        with zipfile.ZipFile(pptx) as z:
            need_rub = any((_SLIDE_PART_RE.match(n) or _CHART_PART_RE.match(n)) and "₽".encode() in z.read(n) for n in z.namelist())
    except (zipfile.BadZipFile, OSError, KeyError):
        return {}
    if not (need_cyr or need_rub):
        return {}
    from lxml import etree

    from verstka.analysis.shapes import SlideContext, extract_shapes
    from verstka.ingest.package import PptxPackage
    from verstka.schemas.common import ShapeKind

    def fix(run, family, bold: bool) -> bool:
        if not family:
            return False
        bold = bool(bold)
        t = "".join(x.text or "" for x in run.iter(f"{{{_A_NS}}}t"))
        changed = False
        face = render_standin(family) or family  # the family LibreOffice sets the run in (the replacement table)
        sub = cyrillic_standin(family, bold) if _CYRILLIC_RE.search(t) else None
        if sub:
            heavy = not bold and is_heavy_face_name(family)
            _set_run_face(run, sub, heavy)
            face, bold, changed = sub, bold or heavy, True
        if "₽" in t and etree.QName(run).localname == "r":
            # «Avenir Heavy 900 000 ₽» (installed: LibreOffice sets it bold) → a bold «₽»; a missing weight-named face
            # («Open Sans SemiBold») is set by LibreOffice at its own weight (regular) → a regular «₽»
            heavy = not bold and is_heavy_face_name(face) and is_installed(face)
            rub = glyph_standin(face, "₽", bold or heavy)
            if rub:
                changed |= _split_glyph(run, "₽", rub, heavy)
        return changed

    out: dict[str, bytes] = {}
    with PptxPackage(pptx) as pkg:
        for part in pkg.slide_parts:
            try:
                ctx = SlideContext(pkg, part)
                shapes = extract_shapes(pkg, part, ctx)
            except Exception:  # noqa: BLE001 — a slide the analysis cannot read keeps LibreOffice's own fallback
                continue
            changed = False
            for s in shapes:
                el = s.element
                if el is None:
                    continue
                if s.text is not None and s.kind == ShapeKind.sp:
                    tx = el.find("{http://schemas.openxmlformats.org/presentationml/2006/main}txBody")
                    if tx is None:
                        continue
                    for p_el, p_info in zip(tx.findall(f"{{{_A_NS}}}p"), s.text.paragraphs):
                        runs = [c for c in p_el if isinstance(c.tag, str) and etree.QName(c).localname in ("r", "fld")]
                        for r_el, r_info in zip(runs, p_info.runs):
                            changed |= fix(r_el, r_info.font, r_info.bold)
                elif s.kind == ShapeKind.graphic_frame:
                    # table cells: their explicit faces (a table style's face stays LibreOffice's)
                    for r_el in list(el.iter(f"{{{_A_NS}}}r")):
                        latin = r_el.find(f"{{{_A_NS}}}rPr/{{{_A_NS}}}latin")
                        fam = latin.get("typeface") if latin is not None else None
                        if fam and fam.startswith("+"):
                            fam = ctx.resolver.font_for(fam)
                        rpr = r_el.find(f"{{{_A_NS}}}rPr")
                        changed |= fix(r_el, fam, rpr is not None and rpr.get("b") in ("1", "true"))
            if changed:
                out[part] = etree.tostring(pkg.xml(part), xml_declaration=True, encoding="UTF-8", standalone=True)
        for part in pkg.part_names:
            if not _CHART_PART_RE.match(part):
                continue
            root = pkg.xml(part)
            changed = False

            def set_face(latin, fam: str, props, bold: bool) -> None:
                latin.set("typeface", fam)
                for attr in ("panose", "pitchFamily", "charset"):
                    latin.attrib.pop(attr, None)
                if bold and props is not None:
                    props.set("b", "1")

            if need_cyr and _CYRILLIC_RE.search("".join(root.itertext())):
                for latin in root.iter(f"{{{_A_NS}}}latin"):
                    fam = latin.get("typeface") or ""
                    props = latin.getparent()
                    bold = props is not None and props.get("b") in ("1", "true")
                    sub = cyrillic_standin(fam, bold)
                    if sub:
                        set_face(latin, sub, props, not bold and is_heavy_face_name(fam))
                        changed = True
            # «₽» of a number format (data labels, a value axis): the element's own text face → one with «₽» — a
            # format's literal cannot get a run of its own
            for fmt in root.iter(f"{{{_C_NS}}}numFmt"):
                owner = fmt.getparent()
                txpr = owner.find(f"{{{_C_NS}}}txPr") if owner is not None and "₽" in (fmt.get("formatCode") or "") else None
                for latin in txpr.iter(f"{{{_A_NS}}}latin") if txpr is not None else ():
                    fam = latin.get("typeface") or ""
                    props = latin.getparent()
                    bold = props is not None and props.get("b") in ("1", "true")
                    heavy = not bold and is_heavy_face_name(fam) and is_installed(fam)
                    rub = glyph_standin(render_standin(fam) or fam, "₽", bold or heavy) if fam else None
                    if rub:
                        set_face(latin, rub, props, heavy)
                        changed = True
            if changed:
                out[part] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    return out


def _xml_attr(text: str) -> str:
    return html.escape(text, quote=True)


def _write_font_table(profile: Path, pairs: dict[str, str]) -> None:
    """Seed a fresh LibreOffice profile with a font replacement table (Tools ▸ Options ▸ Fonts, «Always»): only
    entries applied always reach a PDF export, so the table must list missing families only."""
    if not pairs:
        return
    user = profile / "user"
    user.mkdir(parents=True, exist_ok=True)
    items = [
        '<item oor:path="/org.openoffice.Office.Common/Font/Substitution"><prop oor:name="Replacement" oor:op="fuse">'
        "<value>true</value></prop></item>"
    ]
    for i, (fam, sub) in enumerate(sorted(pairs.items())):
        items.append(
            f'<item oor:path="/org.openoffice.Office.Common/Font/Substitution/FontPairs"><node oor:name="_{i}" oor:op="replace">'
            '<prop oor:name="Always" oor:op="fuse"><value>true</value></prop>'
            '<prop oor:name="OnScreenOnly" oor:op="fuse"><value>false</value></prop>'
            f'<prop oor:name="ReplaceFont" oor:op="fuse"><value>{_xml_attr(fam)}</value></prop>'
            f'<prop oor:name="SubstituteFont" oor:op="fuse"><value>{_xml_attr(sub)}</value></prop></node></item>'
        )
    (user / "registrymodifications.xcu").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        + "\n".join(items)
        + "\n</oor:items>\n",
        encoding="utf-8",
    )


class RenderError(RuntimeError):
    pass


def _runnable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _lo_version(path: str) -> tuple[int, ...]:
    """/opt/libreoffice24.8/program/soffice → (24, 8): the newest of several official builds goes first."""
    return tuple(int(x) for x in re.findall(r"\d+", Path(path).parent.parent.name))


def find_soffice() -> Optional[str]:
    """LibreOffice's `soffice`: $VERSTKA_SOFFICE when it is set (a path or a command), then PATH (`soffice`,
    `libreoffice`), the macOS app, a distribution's package (/usr/lib/libreoffice/program) and the official .deb/.rpm
    builds, which install into /opt/libreofficeX.Y/program and put no `soffice` on PATH (the newest first)."""
    own = (os.environ.get("VERSTKA_SOFFICE") or "").strip()
    if own:
        found = shutil.which(own) or (own if _runnable(own) else None)
        if found:
            return found
        log.warning("VERSTKA_SOFFICE=%s is not a runnable soffice: looking for LibreOffice elsewhere", own)
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    import glob

    candidates = [_MAC_SOFFICE, "/usr/lib/libreoffice/program/soffice", "/usr/lib64/libreoffice/program/soffice"]
    candidates += sorted(glob.glob("/opt/libreoffice*/program/soffice"), key=_lo_version, reverse=True)
    return next((c for c in candidates if _runnable(c)), None)


def find_pdftoppm() -> Optional[str]:
    return shutil.which("pdftoppm")


_LAYOUT_PART_RE = re.compile(r"^ppt/(slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml$")
_SERVICE_PH = {"sldNum", "dt", "ftr", "hdr"}


def _blank_prompts(xml: bytes) -> bytes:
    """Empty the prompt text («Образец текста», «Click to edit…») of every content placeholder of a layout/master."""
    from lxml import etree

    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main", "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    root = etree.fromstring(xml)
    changed = False
    for sp in root.iterfind(".//p:sp", ns):
        ph = sp.find("p:nvSpPr/p:nvPr/p:ph", ns)
        if ph is None or ph.get("type") in _SERVICE_PH:
            continue
        for t in sp.iterfind(".//a:r/a:t", ns):
            if t.text:
                t.text = ""
                changed = True
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True) if changed else xml


_OPAQUE_MEMO: dict[tuple[int, int], Optional[bytes]] = {}
_OPAQUE_MIN_PX = 1_000_000  # a picture of fewer pixels costs LibreOffice nothing worth the work


def _without_opaque_alpha(data: bytes) -> Optional[bytes]:
    """A big PNG whose alpha channel is opaque everywhere, re-encoded without it (the same pixels); None for any other
    picture. LibreOffice writes an alpha channel into the PDF as a soft mask however opaque it is: the four 4K
    backgrounds of LCT took it 15 of the 20 seconds of a deck's conversion. The PNG header says the size and whether
    there is an alpha channel at all (colour type 6 or 4) before anything is decoded."""
    if len(data) < 26 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR" or data[25] not in (4, 6):
        return None
    if int.from_bytes(data[16:20], "big") * int.from_bytes(data[20:24], "big") < _OPAQUE_MIN_PX:
        return None
    key = (len(data), hash(data))
    if key in _OPAQUE_MEMO:
        return _OPAQUE_MEMO[key]
    got: Optional[bytes] = None
    try:
        from io import BytesIO

        from PIL import Image

        im = Image.open(BytesIO(data))
        if im.mode in ("RGBA", "LA") and im.getchannel("A").getextrema()[0] == 255:
            buf = BytesIO()
            im.convert("RGB" if im.mode == "RGBA" else "L").save(buf, format="PNG", compress_level=1)
            got = buf.getvalue()
    except Exception as e:  # noqa: BLE001 — the picture goes as it is
        log.debug("opaque alpha probe failed: %s", e)
    if len(_OPAQUE_MEMO) >= 64:
        _OPAQUE_MEMO.clear()
    _OPAQUE_MEMO[key] = got
    return got


_DRAWN_PART_RE = re.compile(r"^ppt/(slides/slide|slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml$")
_GRAY_MEMO: dict[tuple[int, int], Optional[bytes]] = {}


def _gray_with_alpha(data: bytes) -> Optional[bytes]:
    """A picture with transparent pixels turned grey as PowerPoint's «grayscale» shows it, its transparency kept (PNG);
    None for a picture without transparency (LibreOffice draws those right) or an unreadable one."""
    key = (len(data), hash(data))
    if key in _GRAY_MEMO:
        return _GRAY_MEMO[key]
    got: Optional[bytes] = None
    try:
        from io import BytesIO

        from PIL import Image

        im = Image.open(BytesIO(data))
        if im.mode in ("P", "PA", "LA", "La", "RGBa") or "transparency" in im.info:
            im = im.convert("RGBA")
        if "A" in im.getbands() and im.getchannel("A").getextrema()[0] < 255:
            a = im.getchannel("A")
            g = im.convert("RGB").convert("L")
            buf = BytesIO()
            Image.merge("LA", (g, a)).save(buf, format="PNG", compress_level=1)
            got = buf.getvalue()
    except Exception as e:  # noqa: BLE001 — the picture goes as it is
        log.debug("grayscale bake failed: %s", e)
    if len(_GRAY_MEMO) >= 32:
        _GRAY_MEMO.clear()
    _GRAY_MEMO[key] = got
    return got


def _baked_grayscale(zin: zipfile.ZipFile, own: Optional[dict[str, bytes]] = None) -> dict[str, bytes]:
    """Parts to write instead of (or beside) the package's own for LibreOffice: a picture with transparent pixels drawn
    with PowerPoint's «grayscale» effect (`a:grayscl`) is drawn by LibreOffice with its transparent pixels black — a
    building shot whose sky is transparent became a black diamond under a dark grey cover title, and the preview, the
    PDF and the designer's eyes all saw dark grey on black where PowerPoint shows it on white. Such a picture is
    given, in the render copy only, as a grey picture with its transparency (a new media part, the slide's
    relationship pointed at it) and the effect is dropped. `own`: parts already rewritten for the render (read from
    there). {} when no part draws one."""
    from lxml import etree

    a_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    r_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    names = set(zin.namelist())
    own = own or {}

    def read(n: str) -> bytes:
        return own[n] if n in own else zin.read(n)

    out: dict[str, bytes] = {}
    baked: dict[str, str] = {}  # source media → the grey media part
    for name in sorted(names):
        if not _DRAWN_PART_RE.match(name):
            continue
        data = read(name)
        if b"grayscl" not in data:
            continue
        rels_name = name.rsplit("/", 1)[0] + "/_rels/" + name.rsplit("/", 1)[1] + ".rels"
        if rels_name not in names:
            continue
        try:
            root = etree.fromstring(data)
            rels = etree.fromstring(read(rels_name))
        except etree.XMLSyntaxError:
            continue
        by_id = {r.get("Id"): r for r in rels}
        changed = False
        for blip in root.iter(f"{{{a_ns}}}blip"):
            gray = blip.find(f"{{{a_ns}}}grayscl")
            rid = blip.get(f"{{{r_ns}}}embed")
            rel = by_id.get(rid)
            if gray is None or rel is None or rel.get("TargetMode") == "External":
                continue
            target = rel.get("Target") or ""
            src = target.lstrip("/") if target.startswith("/") else os.path.normpath(os.path.join(name.rsplit("/", 1)[0], target)).replace(os.sep, "/")
            if src not in names:
                continue
            if src not in baked:
                grey = _gray_with_alpha(zin.read(src))
                if grey is None:
                    continue
                dst = f"ppt/media/verstka-grey-{len(baked) + 1}.png"
                while dst in names:
                    dst = dst.replace(".png", "-x.png")
                baked[src] = dst
                out[dst] = grey
            new_id = f"rIdVg{len(by_id) + 1}"
            while new_id in by_id:
                new_id += "x"
            el = etree.SubElement(rels, f"{{{rel_ns}}}Relationship")
            el.set("Id", new_id)
            el.set("Type", rel.get("Type"))
            el.set("Target", "/" + baked[src])
            by_id[new_id] = el
            blip.set(f"{{{r_ns}}}embed", new_id)
            blip.remove(gray)
            changed = True
        if changed:
            out[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            out[rels_name] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True)
    if baked and "[Content_Types].xml" in names:
        ct = read("[Content_Types].xml")
        if b'Extension="png"' not in ct and b"Extension='png'" not in ct:
            out["[Content_Types].xml"] = ct.replace(b"<Default ", b'<Default Extension="png" ContentType="image/png"/><Default ', 1)
    return out


_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _plate_fill(sp) -> bool:
    """A layout placeholder that paints: its own fill (solid, gradient, picture, pattern) or its style's fill."""
    sppr = sp.find(f"{{{_P_NS}}}spPr")
    if sppr is not None:
        if sppr.find(f"{{{_A_NS}}}noFill") is not None:
            return False
        if any(sppr.find(f"{{{_A_NS}}}{t}") is not None for t in ("solidFill", "gradFill", "blipFill", "pattFill")):
            return True
    ref = sp.find(f"{{{_P_NS}}}style/{{{_A_NS}}}fillRef")
    return ref is not None and (ref.get("idx") or "0") != "0"


def _hidden_layout_plates(zin: zipfile.ZipFile, own: Optional[dict[str, bytes]] = None) -> dict[str, bytes]:
    """Parts rewritten for LibreOffice so that a layout's painted placeholders show only where a slide uses them, as in
    PowerPoint. PowerPoint never draws a layout's placeholder on a slide that has no shape of its own for it;
    LibreOffice imports such placeholders as plain shapes of the layout and draws them on every slide (a blue circle
    and a bar of the template's sample, painted «Текст» placeholders, stood over the photo of every slide set on that
    layout, and the designer's eyes judged them). In the render copy the layout's placeholder stops painting, and a
    slide that uses it gets the layout's paint written on its own shape (its geometry, fill, outline and style when
    it sets none of its own). {} when no layout has such a placeholder."""
    import copy

    from lxml import etree

    own = own or {}

    def read(n: str) -> bytes:
        return own[n] if n in own else zin.read(n)

    def key_of(ph) -> tuple:
        return ("idx", ph.get("idx")) if ph.get("idx") is not None else ("type", ph.get("type") or "body")

    names = set(zin.namelist())
    layouts: dict[str, Optional[tuple]] = {}  # layout part → (root, {key: layout sp}) of its painted placeholders
    out: dict[str, bytes] = {}
    p_, a_ = f"{{{_P_NS}}}", f"{{{_A_NS}}}"
    for name in sorted(names):
        if not re.match(r"^ppt/slides/slide\d+\.xml$", name):
            continue
        rels_name = "ppt/slides/_rels/" + name.rsplit("/", 1)[1] + ".rels"
        if rels_name not in names:
            continue
        try:
            rels = etree.fromstring(read(rels_name))
        except etree.XMLSyntaxError:
            continue
        lay = next((r.get("Target") for r in rels if (r.get("Type") or "").endswith("/slideLayout")), None)
        if not lay:
            continue
        lay = lay.lstrip("/") if lay.startswith("/") else os.path.normpath(os.path.join("ppt/slides", lay)).replace(os.sep, "/")
        if lay not in names:
            continue
        if lay not in layouts:
            try:
                lroot = etree.fromstring(read(lay))
            except etree.XMLSyntaxError:
                layouts[lay] = None
                continue
            found = {}
            for sp in lroot.iter(p_ + "sp"):
                ph = sp.find(f"{p_}nvSpPr/{p_}nvPr/{p_}ph")
                if ph is None or (ph.get("type") or "body") in _SERVICE_PH or not _plate_fill(sp):
                    continue
                found[key_of(ph)] = copy.deepcopy(sp)  # (the paint as it was, before the layout stops painting)
                sppr = sp.find(p_ + "spPr")
                if sppr is None:
                    sppr = etree.SubElement(sp, p_ + "spPr")
                for t in ("solidFill", "gradFill", "blipFill", "pattFill", "noFill"):
                    for x in sppr.findall(a_ + t):
                        sppr.remove(x)
                nf = etree.Element(a_ + "noFill")
                geo = [i for i, c in enumerate(sppr) if etree.QName(c).localname in ("xfrm", "custGeom", "prstGeom")]
                sppr.insert(geo[-1] + 1 if geo else 0, nf)
                ln = sppr.find(a_ + "ln")
                if ln is None:
                    ln = etree.SubElement(sppr, a_ + "ln")
                for c in list(ln):
                    if etree.QName(c).localname in ("solidFill", "gradFill", "pattFill", "noFill"):
                        ln.remove(c)
                ln.insert(0, etree.Element(a_ + "noFill"))
                st = sp.find(p_ + "style")
                if st is not None:
                    sp.remove(st)
            layouts[lay] = (lroot, found) if found else None
            if found:
                out[lay] = etree.tostring(lroot, xml_declaration=True, encoding="UTF-8", standalone=True)
        got = layouts.get(lay)
        if not got:
            continue
        found = got[1]
        try:
            root = etree.fromstring(read(name))
        except etree.XMLSyntaxError:
            continue
        changed = False
        for sp in root.iter(p_ + "sp"):
            ph = sp.find(f"{p_}nvSpPr/{p_}nvPr/{p_}ph")
            src = found.get(key_of(ph)) if ph is not None else None
            if src is None or _plate_fill(sp):
                continue
            sppr = sp.find(p_ + "spPr")
            if sppr is None:
                sppr = etree.SubElement(sp, p_ + "spPr")
                sp.insert(1, sppr)
            if sppr.find(a_ + "noFill") is not None:
                continue  # the slide itself says «no fill»: nothing is painted in PowerPoint either
            lsp = src.find(p_ + "spPr")
            for t in ("xfrm", "custGeom", "prstGeom"):
                if sppr.find(a_ + t) is None and lsp is not None and lsp.find(a_ + t) is not None:
                    if t != "xfrm" and (sppr.find(a_ + "custGeom") is not None or sppr.find(a_ + "prstGeom") is not None):
                        continue
                    sppr.append(copy.deepcopy(lsp.find(a_ + t)))
            for t in ("solidFill", "gradFill", "blipFill", "pattFill"):
                if lsp is not None and lsp.find(a_ + t) is not None:
                    sppr.append(copy.deepcopy(lsp.find(a_ + t)))
                    break
            if sppr.find(a_ + "ln") is None and lsp is not None and lsp.find(a_ + "ln") is not None:
                sppr.append(copy.deepcopy(lsp.find(a_ + "ln")))
            # (spPr children in schema order: xfrm, geometry, fill, ln)
            order = {"xfrm": 0, "custGeom": 1, "prstGeom": 1, "noFill": 2, "solidFill": 2, "gradFill": 2, "blipFill": 2, "pattFill": 2, "grpFill": 2, "ln": 3}
            kids = sorted(list(sppr), key=lambda c: order.get(etree.QName(c).localname, 4))
            for c in kids:
                sppr.append(c)
            if sp.find(p_ + "style") is None and src.find(p_ + "style") is not None:
                tx = sp.find(p_ + "txBody")
                st = copy.deepcopy(src.find(p_ + "style"))
                if tx is not None:
                    tx.addprevious(st)
                else:
                    sp.append(st)
            changed = True
        if changed:
            out[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    return out


def render_copy(pptx: Path, out_dir: Path) -> Path:
    """A copy of the deck for LibreOffice only, named like the original (the PDF takes the stem).

    PowerPoint never shows layout placeholders on a slide, but LibreOffice imports the extra placeholders of a
    custom layout as plain master shapes: their prompt text shows through wherever the sample covered it with a
    card that the renderer removed. Runs of Cyrillic text in an installed face without Cyrillic are set in one
    stand-in face, a «₽» the face lacks in a face of its class (`run_faces`). A big PNG with an alpha channel opaque
    everywhere goes without it (`_without_opaque_alpha`). A transparent picture under PowerPoint's grayscale effect goes
    grey already (`_baked_grayscale`); a painted placeholder of a layout paints only on the slides that use it
    (`_hidden_layout_plates`). The .pptx handed to the user is not touched.
    """
    from verstka import pkgzip

    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / pptx.name
    try:
        faces = run_faces(pptx)  # Cyrillic runs of faces without Cyrillic, «₽» of faces without it → stand-in faces
    except Exception as e:  # noqa: BLE001 — a font probe never fails a render
        log.warning("cyrillic run faces skipped: %s", e)
        faces = {}
    with zipfile.ZipFile(pptx) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        try:
            # a layout's painted placeholders paint only where a slide uses them, as in PowerPoint
            faces = {**faces, **_hidden_layout_plates(zin, faces)}
        except Exception as e:  # noqa: BLE001 — a render never fails over it
            log.warning("layout plates kept: %s", e)
        try:
            grey = _baked_grayscale(zin, faces)  # pictures LibreOffice greys wrong: grey pixels baked, transparency kept
        except Exception as e:  # noqa: BLE001 — a render never fails over it
            log.warning("grayscale bake skipped: %s", e)
            grey = {}
        for item in zin.infolist():
            name = item.filename
            if name in grey or name in faces:
                data = grey.pop(name) if name in grey else faces[name]  # (grey is built on the other rewrites)
            else:
                data = zin.read(item)
                if name.startswith("ppt/media/"):
                    data = _without_opaque_alpha(data) or data
            if _LAYOUT_PART_RE.match(name):
                data = _blank_prompts(data)
            zout.writestr(pkgzip.entry(item), data)
        for name, data in grey.items():  # the new grey pictures
            zout.writestr(zipfile.ZipInfo(name), data, compress_type=pkgzip.compress_type(name))
    return dst


def pptx_to_pdf(pptx: Path, out_dir: Path, timeout_s: float = 240.0) -> Path:
    soffice = find_soffice()
    if not soffice:
        raise RenderError("LibreOffice (soffice) not found; install it to render slides")
    out_dir.mkdir(parents=True, exist_ok=True)
    _warn_missing_mac_fonts()
    env = os.environ.copy()
    env["SAL_USE_VCLPLUGIN"] = "svp"
    with tempfile.TemporaryDirectory(prefix="verstka_lo_", ignore_cleanup_errors=True) as profile:
        fc = _fontconfig(Path(profile))
        if fc:
            env["FONTCONFIG_FILE"] = fc
        try:
            src = render_copy(Path(pptx), Path(profile) / "src")
        except (zipfile.BadZipFile, OSError, ValueError) as e:  # a broken package still gets its LibreOffice verdict
            log.warning("render copy failed, converting the original: %s", e)
            src = Path(pptx)
        # missing template families → one installed face of their class (see font_replacements)
        pairs = font_replacements(src, available=_bundled_families() if fc else frozenset())
        if pairs:
            log.debug("LibreOffice font stand-ins: %s", pairs)
            _write_font_table(Path(profile) / "profile", pairs)
        cmd = [
            soffice,
            f"-env:UserInstallation={(Path(profile) / 'profile').as_uri()}",
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(src),
        ]
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired as e:
            raise RenderError(f"soffice timed out after {timeout_s}s") from e
    pdf = out_dir / (pptx.stem + ".pdf")
    if proc.returncode != 0 or not pdf.exists():
        raise RenderError(f"soffice failed (rc={proc.returncode}): {proc.stderr[-500:]}")
    return pdf


def pdf_to_images(pdf: Path, out_dir: Path, dpi: int = 110, prefix: str = "slide", fmt: str = "jpeg") -> list[Path]:
    pdftoppm = find_pdftoppm()
    if not pdftoppm:
        raise RenderError("pdftoppm (poppler) not found; install poppler to render slides")
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{prefix}-*.{ 'jpg' if fmt == 'jpeg' else fmt}"):
        old.unlink()
    flag = "-jpeg" if fmt == "jpeg" else "-png"
    cmd = [pdftoppm, flag, "-r", str(dpi), str(pdf), str(out_dir / prefix)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RenderError(f"pdftoppm failed: {proc.stderr[-500:]}")
    ext = "jpg" if fmt == "jpeg" else fmt
    produced = sorted(out_dir.glob(f"{prefix}-*.{ext}"), key=lambda p: int(p.stem.rsplit("-", 1)[-1]))
    # normalize names to prefix-NNN.ext (pdftoppm pads by page count)
    final: list[Path] = []
    for p in produced:
        n = int(p.stem.rsplit("-", 1)[-1])
        target = out_dir / f"{prefix}-{n:03d}.{ext}"
        if p != target:
            p.rename(target)
        final.append(target)
    return final


def render_slides(pptx: Path, out_dir: Path, dpi: int = 110, keep_pdf: bool = True) -> list[Path]:
    """Render every slide to `out_dir/slide-NNN.jpg` (1-based). Returns paths in slide order."""
    pptx = Path(pptx)
    out_dir = Path(out_dir)
    pdf = pptx_to_pdf(pptx, out_dir)
    images = pdf_to_images(pdf, out_dir, dpi=dpi)
    if not keep_pdf:
        pdf.unlink(missing_ok=True)
    log.info("rendered %d slides from %s", len(images), pptx.name)
    return images
