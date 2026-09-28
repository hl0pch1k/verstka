"""Template workspace: cache directory keyed by the file hash."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# Ids that may be joined to a workspace directory: one path segment, no dots, no separators, no control chars.
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def file_sha256(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def default_workspace_root() -> Path:
    return Path(os.environ.get("VERSTKA_WORKSPACE", "workspace")).resolve()


@dataclass
class TemplateWorkspace:
    template_id: str
    dir: Path
    source: Path  # copy of the original pptx inside the workspace

    @classmethod
    def create(cls, pptx: Path | str, root: Optional[Path | str] = None, display_name: Optional[str] = None) -> "TemplateWorkspace":
        """`display_name`: the name the person gave the file (a converted «Бренд.potx» is analysed as «Бренд.pptx»)."""
        pptx = Path(pptx)
        root = Path(root) if root else default_workspace_root()
        template_id = file_sha256(pptx)[:16]
        d = root / "templates" / template_id
        d.mkdir(parents=True, exist_ok=True)
        src = d / "source.pptx"
        if not src.exists():
            shutil.copyfile(pptx, src)
        (d / "meta.txt").write_text(f"{display_name or pptx.name}\n", encoding="utf-8")
        return cls(template_id=template_id, dir=d, source=src)

    @classmethod
    def open(cls, template_id: str, root: Optional[Path | str] = None) -> "TemplateWorkspace":
        root = Path(root) if root else default_workspace_root()
        if not SAFE_ID_RE.fullmatch(template_id or ""):
            raise FileNotFoundError(f"invalid template id {template_id!r}")
        d = root / "templates" / template_id
        if not d.is_dir():
            raise FileNotFoundError(f"template workspace {template_id} not found under {root}")
        return cls(template_id=template_id, dir=d, source=d / "source.pptx")

    @property
    def original_name(self) -> str:
        meta = self.dir / "meta.txt"
        return meta.read_text(encoding="utf-8").strip() if meta.exists() else "template.pptx"

    @property
    def slides_dir(self) -> Path:
        return self.dir / "slides"

    @property
    def thumbs_dir(self) -> Path:
        return self.dir / "thumbs"

    @property
    def assets_dir(self) -> Path:
        return self.dir / "assets"

    @property
    def manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    @property
    def gallery_path(self) -> Path:
        return self.dir / "gallery.html"

    @property
    def is_analyzed(self) -> bool:
        return self.manifest_path.exists()

    def slide_image(self, index_1based: int) -> Path:
        return self.slides_dir / f"slide-{index_1based:03d}.jpg"

    def slide_images(self) -> list[Path]:
        return sorted(self.slides_dir.glob("slide-*.jpg"))
