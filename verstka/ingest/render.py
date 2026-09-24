"""Render PPTX slides to JPEG via LibreOffice (PPTX → PDF) and poppler (PDF → images)."""

from __future__ import annotations

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
    card that the renderer removed. The .pptx handed to the user is not touched.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / pptx.name
    with zipfile.ZipFile(pptx) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if _LAYOUT_PART_RE.match(item.filename):
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
