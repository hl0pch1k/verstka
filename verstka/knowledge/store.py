"""The knowledge base on disk: `<workspace>/knowledge/<id>/`.

    meta.json                       {id, name, created_at, docs: [...]}
    docs/<doc id>/source.<ext>      the file as it came (a page: the answer's bytes)
    docs/<doc id>/text.md           the document as Markdown (what the person can read back)
    docs/<doc id>/fragments.json    its fragments with their tokens (the search reads these)

A person adds documents (DOCX, PDF, MD, TXT, HTML; a .zip of them or a folder — the files one by one) and links to
public pages. Each document is read once (verstka/ingest/documents.py), cut into fragments and indexed; the search is
local (BM25, verstka/knowledge/index.py)."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import secrets
import shutil
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from verstka.ingest.documents import ALL_EXTS, DocumentError, DocumentText, read_document
from verstka.knowledge.index import Fragment, Search, fragments_of

log = logging.getLogger(__name__)

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MAX_DOCS = 60
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ZIP_MEMBERS = 120
MAX_ZIP_UNPACKED = 200 * 1024 * 1024
MAX_CHARS = 4_000_000  # all documents' text together
_LOCK = threading.Lock()


class KnowledgeError(ValueError):
    """A request the base cannot take — the message is for the person (Russian)."""


@dataclass
class Added:
    docs: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # {"name", "reason"}


def kb_root(workspace_root: Path | str) -> Path:
    return Path(workspace_root) / "knowledge"


def _atomic(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _plain_name(name: str) -> str:
    n = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    n = re.sub(r"[\x00-\x1f]", "", n)
    return n[:160] or "документ"


class KnowledgeBase:
    def __init__(self, kid: str, path: Path) -> None:
        self.id = kid
        self.dir = path
        self._frags: Optional[list[Fragment]] = None
        self._search: Optional[Search] = None

    # ---------------------------------------------------------------- open / create

    @classmethod
    def create(cls, workspace_root: Path | str, name: str = "") -> "KnowledgeBase":
        root = kb_root(workspace_root)
        root.mkdir(parents=True, exist_ok=True)
        kid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        d = root / kid
        (d / "docs").mkdir(parents=True)
        _atomic(d / "meta.json", {"id": kid, "name": (name or "").strip()[:120] or "База знаний", "created_at": time.time(), "docs": []})
        return cls(kid, d)

    @classmethod
    def open(cls, workspace_root: Path | str, kid: str) -> Optional["KnowledgeBase"]:
        if not SAFE_ID_RE.fullmatch(kid or ""):
            return None
        d = kb_root(workspace_root) / kid
        if not (d / "meta.json").is_file():
            return None
        return cls(kid, d)

    def meta(self) -> dict:
        try:
            return json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"id": self.id, "name": "База знаний", "docs": []}

    def _write_meta(self, m: dict) -> None:
        _atomic(self.dir / "meta.json", m)
        self._frags = None
        self._search = None

    @property
    def docs(self) -> list[dict]:
        return list(self.meta().get("docs") or [])

    def summary(self) -> dict:
        m = self.meta()
        docs = m.get("docs") or []
        return {"id": self.id, "name": m.get("name") or "База знаний", "created_at": m.get("created_at"), "docs": docs,
                "fragments": sum(int(d.get("fragments") or 0) for d in docs), "chars": sum(int(d.get("chars") or 0) for d in docs)}

    def delete(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    # ---------------------------------------------------------------- adding

    def add_file(self, name: str, data: bytes, *, url: Optional[str] = None) -> Added:
        """A document, or every document of a .zip; what could not be read is in `skipped` with the reason."""
        name = _plain_name(name)
        out = Added()
        if data[:2] == b"PK" and (name.lower().endswith(".zip") or not name.lower().endswith((".docx", ".docm", ".dotx", ".odt"))):
            if not _is_docx_package(data):
                for mname, mdata, reason in _zip_members(name, data):
                    if reason:
                        out.skipped.append({"name": mname, "reason": reason})
                        continue
                    self._add_one(mname, mdata, None, out)
                if not out.docs and not out.skipped:
                    out.skipped.append({"name": name, "reason": "в архиве нет документов"})
                return out
        self._add_one(name, data, url, out)
        return out

    def add_url(self, url: str, *, transport: Any = None, resolve: Any = None, timeout_s: Optional[float] = None) -> Added:
        from verstka.knowledge.web import FetchError, fetch, page_name

        if any((d.get("url") or "") == url.strip() for d in self.docs):
            raise KnowledgeError("Эта страница уже в базе")
        try:
            page = fetch(url, transport=transport, resolve=resolve, **({"timeout_s": timeout_s} if timeout_s else {}))
        except FetchError as e:
            raise KnowledgeError(str(e)) from e
        out = Added()
        self._add_one(page_name(page), page.data, page.url, out)
        if out.skipped and not out.docs:
            raise KnowledgeError(out.skipped[0]["reason"])
        return out

    def _add_one(self, name: str, data: bytes, url: Optional[str], out: Added) -> None:
        if len(data) > MAX_FILE_BYTES:
            out.skipped.append({"name": name, "reason": f"больше {MAX_FILE_BYTES // (1024 * 1024)} МБ"})
            return
        ext = Path(name).suffix.lower()
        if not url and ext and ext not in ALL_EXTS:
            out.skipped.append({"name": name, "reason": "этот формат не читаю — подходят DOCX, PDF, MD, TXT, HTML"})
            return
        sha = hashlib.sha256(data).hexdigest()
        with _LOCK:
            m = self.meta()
            docs = m.get("docs") or []
            same = next((d for d in docs if d.get("sha256") == sha), None)
            if same is not None:
                out.skipped.append({"name": name, "reason": f"уже в базе как «{same.get('name')}»"})
                return
            if len(docs) >= MAX_DOCS:
                out.skipped.append({"name": name, "reason": f"в базе уже {MAX_DOCS} документов — уберите ненужные"})
                return
        try:
            doc = read_document(name, data)
        except DocumentError as e:
            out.skipped.append({"name": name, "reason": str(e)})
            return
        except Exception as e:  # noqa: BLE001 - a reader's slip on a broken file: said in words
            log.warning("knowledge: %s not read", name, exc_info=True)
            out.skipped.append({"name": name, "reason": f"не читается ({type(e).__name__})"})
            return
        did = sha[:12]
        frags = fragments_of(doc, did)
        if not frags:
            out.skipped.append({"name": name, "reason": "в документе нет текста"})
            return
        chars = sum(len(f.text) for f in frags)
        with _LOCK:
            m = self.meta()
            docs = m.get("docs") or []
            if sum(int(d.get("chars") or 0) for d in docs) + chars > MAX_CHARS:
                out.skipped.append({"name": name, "reason": "база знаний переполнена — уберите ненужные документы"})
                return
            ddir = self.dir / "docs" / did
            ddir.mkdir(parents=True, exist_ok=True)
            (ddir / f"source{ext or '.bin'}").write_bytes(data)
            (ddir / "text.md").write_text(doc.markdown(), encoding="utf-8")
            _atomic(ddir / "fragments.json", [f.to_json() for f in frags])
            entry = {
                "id": did, "name": name, "title": doc.title or Path(name).stem, "kind": doc.kind, "url": url, "source": "link" if url else "file",
                "sha256": sha, "added_at": time.time(), "pages": doc.pages, "chars": chars, "fragments": len(frags),
                "tables": len(doc.tables), "headings": doc.headings, "warnings": doc.warnings[:5],
            }
            docs.append(entry)
            m["docs"] = docs
            self._write_meta(m)
        out.docs.append(entry)

    def remove(self, doc_id: str) -> bool:
        if not SAFE_ID_RE.fullmatch(doc_id or ""):
            return False
        with _LOCK:
            m = self.meta()
            docs = m.get("docs") or []
            keep = [d for d in docs if d.get("id") != doc_id]
            if len(keep) == len(docs):
                return False
            m["docs"] = keep
            self._write_meta(m)
        shutil.rmtree(self.dir / "docs" / doc_id, ignore_errors=True)
        return True

    # ---------------------------------------------------------------- reading

    def doc(self, doc_id: str) -> Optional[dict]:
        return next((d for d in self.docs if d.get("id") == doc_id), None)

    def fragments(self) -> list[Fragment]:
        if self._frags is None:
            out: list[Fragment] = []
            for d in self.docs:
                p = self.dir / "docs" / str(d.get("id")) / "fragments.json"
                try:
                    out += [Fragment.from_json(x) for x in json.loads(p.read_text(encoding="utf-8"))]
                except (OSError, json.JSONDecodeError, TypeError):
                    log.warning("knowledge: fragments of %s not read", d.get("id"))
            self._frags = out
        return self._frags

    def search(self, query: str, k: int = 8) -> list[tuple[Fragment, float]]:
        if self._search is None:
            self._search = Search(self.fragments())
        return self._search.top(query, k)

    def text_md(self, doc_id: str) -> Optional[str]:
        if not SAFE_ID_RE.fullmatch(doc_id or ""):
            return None
        p = self.dir / "docs" / doc_id / "text.md"
        return p.read_text(encoding="utf-8") if p.is_file() else None


def _is_docx_package(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return "word/document.xml" in z.namelist()
    except zipfile.BadZipFile:
        return False


def _zip_members(name: str, data: bytes):
    """(member name, bytes, reason when skipped) of a .zip archive: documents only, hidden and system files out,
    within MAX_ZIP_MEMBERS and MAX_ZIP_UNPACKED."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        yield name, b"", "архив повреждён"
        return
    with z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        total = 0
        taken = 0
        for i in infos:
            base = i.filename.replace("\\", "/").rsplit("/", 1)[-1]
            if not base or base.startswith((".", "~$")) or "__MACOSX/" in i.filename:
                continue
            if Path(base).suffix.lower() not in ALL_EXTS:
                yield base, b"", "этот формат не читаю — подходят DOCX, PDF, MD, TXT, HTML"
                continue
            taken += 1
            if taken > MAX_ZIP_MEMBERS:
                yield base, b"", f"в архиве больше {MAX_ZIP_MEMBERS} документов — остальные не взяты"
                break
            total += i.file_size
            if total > MAX_ZIP_UNPACKED or i.file_size > MAX_FILE_BYTES:
                yield base, b"", "архив слишком большой в распакованном виде"
                break
            try:
                yield base, z.read(i), None
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
                yield base, b"", "не распаковывается (повреждён или защищён паролем)"


def list_bases(workspace_root: Path | str) -> list[dict]:
    root = kb_root(workspace_root)
    out = []
    for d in sorted(root.glob("*"), reverse=True) if root.is_dir() else []:
        kb = KnowledgeBase.open(workspace_root, d.name)
        if kb is not None:
            s = kb.summary()
            out.append({k: s[k] for k in ("id", "name", "created_at", "fragments")} | {"docs": len(s["docs"])})
    return out


__all__ = ["Added", "KnowledgeBase", "KnowledgeError", "MAX_DOCS", "MAX_FILE_BYTES", "kb_root", "list_bases"]
