"""PDF export through LibreOffice."""

from __future__ import annotations

import shutil
from pathlib import Path

from verstka.ingest.render import pptx_to_pdf


def export_pdf(pptx: Path | str, out: Path | str | None = None) -> Path:
    pptx = Path(pptx)
    out = Path(out) if out else pptx.with_suffix(".pdf")
    pdf = pptx_to_pdf(pptx, out.parent)
    if pdf != out:
        shutil.move(str(pdf), str(out))
    return out
