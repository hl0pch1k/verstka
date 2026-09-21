"""Filesystem-backed store for templates and generations under the workspace root."""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from verstka.ingest.workspace import TemplateWorkspace, default_workspace_root
from verstka.schemas.template import TemplateManifest


class Store:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else default_workspace_root()
        self.uploads = self.root / "uploads"
        self.runs = self.root / "runs"
        for d in (self.root, self.uploads, self.runs, self.root / "templates"):
            d.mkdir(parents=True, exist_ok=True)

    # ---- templates ----------------------------------------------------------------
    def save_upload(self, filename: str, data: bytes) -> Path:
        safe = "".join(ch for ch in filename if ch.isalnum() or ch in "._- ()") or "upload.pptx"
        path = self.uploads / f"{uuid.uuid4().hex[:8]}_{safe}"
        path.write_bytes(data)
        return path

    def list_templates(self) -> list[dict]:
        out = []
        for d in sorted((self.root / "templates").glob("*")):
            mp = d / "manifest.json"
            if mp.exists():
                try:
                    m = json.loads(mp.read_text(encoding="utf-8"))
                    out.append({"template_id": m["template_id"], "source_file": m.get("source_file"), "n_slides": m.get("n_slides"), "n_patterns": len(m.get("patterns", [])), "analyzed_at": mp.stat().st_mtime})
                except Exception:  # noqa: BLE001
                    continue
        out.sort(key=lambda t: -t["analyzed_at"])
        return out

    def manifest(self, template_id: str) -> Optional[TemplateManifest]:
        try:
            ws = TemplateWorkspace.open(template_id, self.root)
        except FileNotFoundError:
            return None
        if not ws.is_analyzed:
            return None
        return TemplateManifest.model_validate_json(ws.manifest_path.read_text(encoding="utf-8"))

    def workspace(self, template_id: str) -> TemplateWorkspace:
        return TemplateWorkspace.open(template_id, self.root)

    # ---- generations --------------------------------------------------------------
    def new_generation_dir(self) -> tuple[str, Path]:
        gid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        d = self.runs / gid
        d.mkdir(parents=True, exist_ok=True)
        return gid, d

    def generation_dir(self, gid: str) -> Optional[Path]:
        d = self.runs / gid
        return d if d.is_dir() else None

    def list_generations(self) -> list[dict]:
        out = []
        for d in sorted(self.runs.glob("*"), reverse=True):
            meta = d / "generation.json"
            if meta.exists():
                try:
                    out.append(json.loads(meta.read_text(encoding="utf-8")))
                except Exception:  # noqa: BLE001
                    continue
        return out

    def write_generation_meta(self, gid: str, data: dict) -> None:
        d = self.runs / gid
        (d / "generation.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_generation_meta(self, gid: str) -> Optional[dict]:
        p = self.runs / gid / "generation.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def delete_generation(self, gid: str) -> bool:
        d = self.runs / gid
        if d.is_dir():
            shutil.rmtree(d)
            return True
        return False
