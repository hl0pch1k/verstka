"""Render PPTX slides to JPEG via LibreOffice (PPTX → PDF) and poppler (PDF → images)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_MAC_SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


class RenderError(RuntimeError):
    pass


def find_soffice() -> Optional[str]:
    return shutil.which("soffice") or (_MAC_SOFFICE if os.path.exists(_MAC_SOFFICE) else None)


def find_pdftoppm() -> Optional[str]:
    return shutil.which("pdftoppm")


def pptx_to_pdf(pptx: Path, out_dir: Path, timeout_s: float = 240.0) -> Path:
    soffice = find_soffice()
    if not soffice:
        raise RenderError("LibreOffice (soffice) not found; install it to render slides")
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["SAL_USE_VCLPLUGIN"] = "svp"
    with tempfile.TemporaryDirectory(prefix="verstka_lo_", ignore_cleanup_errors=True) as profile:
        cmd = [
            soffice,
            f"-env:UserInstallation={Path(profile).as_uri()}",
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(pptx),
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
