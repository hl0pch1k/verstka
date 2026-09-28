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


def find_soffice() -> Optional[str]:
    return shutil.which("soffice") or (_MAC_SOFFICE if os.path.exists(_MAC_SOFFICE) else None)


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


def render_copy(pptx: Path, out_dir: Path) -> Path:
    """A copy of the deck for LibreOffice only, named like the original (the PDF takes the stem).

    PowerPoint never shows layout placeholders on a slide, but LibreOffice imports the extra placeholders of a
    custom layout as plain master shapes: their prompt text shows through wherever the sample covered it with a
    card that the renderer removed. Runs of Cyrillic text in an installed face without Cyrillic are set in one
    stand-in face, a «₽» the face lacks in a face of its class (`run_faces`). The .pptx handed to the user is not
    touched.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / pptx.name
    try:
        faces = run_faces(pptx)  # Cyrillic runs of faces without Cyrillic, «₽» of faces without it → stand-in faces
    except Exception as e:  # noqa: BLE001 — a font probe never fails a render
        log.warning("cyrillic run faces skipped: %s", e)
        faces = {}
    with zipfile.ZipFile(pptx) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in faces:
                data = faces[item.filename]
            elif _LAYOUT_PART_RE.match(item.filename):
                data = _blank_prompts(data)
            zout.writestr(item, data)
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
