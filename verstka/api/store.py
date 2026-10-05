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

from verstka.analysis.rules import with_fresh_derived_rules
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


TITLE_FILE = "title.txt"
TITLE_MAX = 80


def _title_of(tdir: Path) -> Optional[str]:
    """The name a person gave the template in the UI (`title.txt` beside the manifest), if any."""
    try:
        t = (tdir / TITLE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return t or None


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
        safe = "".join(ch for ch in Path(filename).name if ch.isalnum() or ch in "._- ()").lstrip(". ")
        if not safe or not safe.strip("."):
            safe = "upload.pptx"  # «..», «.», dots only: never a path of its own
        # a folder per upload keeps the user's file name intact (it becomes the template's source_file)
        d = self.uploads / uuid.uuid4().hex[:8]
        d.mkdir(parents=True, exist_ok=True)
        return d / safe

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
                    out.append({"template_id": m["template_id"], "source_file": m.get("source_file"), "title": _title_of(d), "n_slides": m.get("n_slides"), "n_patterns": len(m.get("patterns", [])), "analyzed_at": mp.stat().st_mtime, **_card_of(d, m)})
                except Exception:  # noqa: BLE001
                    continue
        out.sort(key=lambda t: -t["analyzed_at"])
        return out

    def template_title(self, template_id: str) -> Optional[str]:
        d = _safe(self.root / "templates", template_id)
        return _title_of(d) if d is not None else None

    def set_template_title(self, template_id: str, title: str) -> Optional[dict]:
        """Rename a template for people: `title.txt` beside the manifest, the file and its analysis stay as they are (the
        manifest's time orders the list, so it is not touched). Spaces are collapsed, the name is cut at TITLE_MAX; an
        empty one brings back the file's name. The template's list entry, or None when there is no such template."""
        d = _safe(self.root / "templates", template_id)
        if d is None or not (d / "manifest.json").exists():
            return None
        clean = " ".join(str(title).split())[:TITLE_MAX].strip()
        path = d / TITLE_FILE
        if clean:
            path.write_text(clean + "\n", encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
        return next((t for t in self.list_templates() if t["template_id"] == template_id), None)

    def manifest(self, template_id: str) -> Optional[TemplateManifest]:
        try:
            ws = TemplateWorkspace.open(template_id, self.root)
        except FileNotFoundError:
            return None
        if not ws.is_analyzed:
            return None
        return with_fresh_derived_rules(TemplateManifest.model_validate_json(ws.manifest_path.read_text(encoding="utf-8")))

    def workspace(self, template_id: str) -> TemplateWorkspace:
        """Raises FileNotFoundError for unknown and for malformed ids."""
        return TemplateWorkspace.open(template_id, self.root)

    def delete_template(self, template_id: str) -> bool:
        """Remove a template from the library: its workspace (analysis, previews, the copy of the file). Decks built on
        it keep their own files and stay viewable; only rebuilding them needs the template again."""
        try:
            ws = TemplateWorkspace.open(template_id, self.root)
        except FileNotFoundError:
            return False
        shutil.rmtree(ws.dir, ignore_errors=True)
        return not ws.dir.exists()

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

    def merge_variant_summary(self, gid: str, strategy: str, fields: dict) -> Optional[dict]:
        """One variant's line of the generation's summary (its score, errors, slide count) updated under the lock, read
        afresh: two jobs on two variants never write back a summary one of them read before the other's change."""
        d = self.generation_dir(gid)
        if d is None:
            return None
        p = d / "generation.json"
        with _META_LOCK:
            meta = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"id": gid}
            summary = meta.get("summary") if isinstance(meta.get("summary"), dict) else {}
            summary[strategy] = {**(summary.get(strategy) or {}), **fields}
            meta["summary"] = summary
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
