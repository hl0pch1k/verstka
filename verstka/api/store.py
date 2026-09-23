"""Filesystem-backed store for templates and generations under the workspace root."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from verstka.ingest.workspace import SAFE_ID_RE, TemplateWorkspace, default_workspace_root
from verstka.schemas.template import TemplateManifest

_META_LOCK = threading.RLock()


def _card_of(tdir: Path, m: dict) -> dict:
    """What a template card in the UI shows without loading the manifest: cover, main colours, main font, format."""
    tid = m["template_id"]
    cover = next((f"thumbs/{p.name}" for p in sorted((tdir / "thumbs").glob("slide-*.jpg"))[:1]), None)
    colors = sorted(m.get("tokens", {}).get("colors", []), key=lambda c: -float(c.get("weight", 0)))
    families = m.get("tokens", {}).get("typography", {}).get("families", [])
    size = m.get("slide_size") or {}
    return {
        "cover_url": f"/api/templates/{tid}/files/{cover}" if cover else None,
        "palette": [c["hex"] for c in colors[:6] if c.get("hex")],
        "font": families[0].get("family") if families else None,
        "aspect": round(size["w"] / size["h"], 4) if size.get("w") and size.get("h") else None,
    }


def _write_json_atomic(path: Path, data: dict) -> None:
    """Readers (the UI polls generation.json while the job thread rewrites it) see the old file or the new one,
    never a truncated one: write aside, then rename over."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

_ID_RE = SAFE_ID_RE


def _safe(base: Path, name: str) -> Optional[Path]:
    """`base/name` when `name` is a plain id (single segment, no dots/separators) that resolves to a direct child of `base`."""
    if not isinstance(name, str) or not _ID_RE.fullmatch(name):
        return None
    base_r = base.resolve()
    target = (base_r / name).resolve()
    if not target.is_relative_to(base_r) or target.parent != base_r:
        return None
    return base / name


class Store:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else default_workspace_root()
        self.uploads = self.root / "uploads"
        self.runs = self.root / "runs"
        for d in (self.root, self.uploads, self.runs, self.root / "templates"):
            d.mkdir(parents=True, exist_ok=True)

    # ---- templates ----------------------------------------------------------------
    def upload_path(self, filename: str) -> Path:
        safe = "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in "._- ()") or "upload.pptx"
        return self.uploads / f"{uuid.uuid4().hex[:8]}_{safe}"

    def save_upload(self, filename: str, data: bytes) -> Path:
        path = self.upload_path(filename)
        path.write_bytes(data)
        return path

    def list_templates(self) -> list[dict]:
        out = []
        for d in sorted((self.root / "templates").glob("*")):
            mp = d / "manifest.json"
            if mp.exists():
                try:
                    m = json.loads(mp.read_text(encoding="utf-8"))
                    out.append({"template_id": m["template_id"], "source_file": m.get("source_file"), "n_slides": m.get("n_slides"), "n_patterns": len(m.get("patterns", [])), "analyzed_at": mp.stat().st_mtime, **_card_of(d, m)})
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
        """Raises FileNotFoundError for unknown and for malformed ids."""
        return TemplateWorkspace.open(template_id, self.root)

    # ---- generations --------------------------------------------------------------
    def new_generation_dir(self) -> tuple[str, Path]:
        gid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        d = self.runs / gid
        d.mkdir(parents=True, exist_ok=True)
        return gid, d

    def generation_dir(self, gid: str) -> Optional[Path]:
        d = _safe(self.runs, gid)
        return d if d is not None and d.is_dir() else None

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

    def write_generation_meta(self, gid: str, data: dict) -> bool:
        d = self.generation_dir(gid)
        if d is None:
            return False
        with _META_LOCK:
            _write_json_atomic(d / "generation.json", data)
        return True

    def merge_generation_meta(self, gid: str, data: dict, only_missing: bool = False) -> Optional[dict]:
        """Read-modify-write under one lock: the job thread and the request thread may both touch generation.json."""
        d = self.generation_dir(gid)
        if d is None:
            return None
        p = d / "generation.json"
        with _META_LOCK:
            meta = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"id": gid}
            for k, v in data.items():
                if not only_missing or k not in meta:
                    meta[k] = v
            _write_json_atomic(p, meta)
        return meta

    def read_generation_meta(self, gid: str) -> Optional[dict]:
        d = self.generation_dir(gid)
        if d is None:
            return None
        p = d / "generation.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def delete_generation(self, gid: str) -> bool:
        d = self.generation_dir(gid)
        if d is not None:
            shutil.rmtree(d)
            return True
        return False
