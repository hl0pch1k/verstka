"""Пакет PPTX в памяти для брендированной копии: части читаются один раз, XML разбирается один раз, изменённые и новые
части (логотипы бренда, связи) записываются при сохранении; картинки не пережимаются (`verstka.pkgzip`)."""

from __future__ import annotations

import io
import posixpath
import zipfile
from pathlib import Path
from typing import Optional

from lxml import etree

from verstka import pkgzip

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
IMG_REL = R + "/image"

Box = tuple[float, float, float, float]  # x, y, w, h в EMU слайда


class Package:
    """Части пакета в памяти: `xml(name)` — разобранная часть (одна на имя), `dirty` — что переписать при `save`."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        with zipfile.ZipFile(self.path) as z:
            self.infos = z.infolist()
            self.data = {i.filename: z.read(i) for i in self.infos}
        self.trees: dict[str, etree._Element] = {}
        self.dirty: set[str] = set()
        self.added: dict[str, bytes] = {}

    def names(self) -> list[str]:
        return [i.filename for i in self.infos] + [n for n in self.added if n not in self.data]

    def has(self, name: str) -> bool:
        return name in self.data or name in self.added

    def read(self, name: str) -> bytes:
        return self.added.get(name) or self.data[name]

    def xml(self, name: str) -> Optional[etree._Element]:
        if name not in self.trees:
            try:
                self.trees[name] = etree.fromstring(self.read(name))
            except (KeyError, etree.XMLSyntaxError):
                return None
        return self.trees[name]

    @staticmethod
    def rels_name(part: str) -> str:
        d, f = posixpath.split(part)
        return posixpath.join(d, "_rels", f + ".rels")

    def rels(self, part: str) -> dict[str, tuple[str, str]]:
        """rId → (тип, цель — имя части); внешние ссылки пропускаются."""
        name = self.rels_name(part)
        root = self.xml(name) if self.has(name) else None
        out: dict[str, tuple[str, str]] = {}
        if root is None:
            return out
        for r in root:
            tgt = r.get("Target") or ""
            if r.get("TargetMode") == "External":
                continue
            full = tgt.lstrip("/") if tgt.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(part), tgt))
            out[r.get("Id") or ""] = (r.get("Type") or "", full)
        return out

    def related(self, part: str, kind: str) -> Optional[str]:
        """Часть, на которую `part` ссылается связью этого вида («slideLayout», «slideMaster», «theme»)."""
        return next((t for typ, t in self.rels(part).values() if typ.endswith("/" + kind)), None)

    def add_rel(self, part: str, rtype: str, target_part: str) -> str:
        name = self.rels_name(part)
        root = self.xml(name) if self.has(name) else None
        if root is None:
            root = etree.Element(f"{{{PR}}}Relationships", nsmap={None: PR})
            self.trees[name] = root
            self.added.setdefault(name, b"")
        ids = {r.get("Id") for r in root}
        n = 1
        while f"rIdBrand{n}" in ids:
            n += 1
        rid = f"rIdBrand{n}"
        rel = etree.SubElement(root, f"{{{PR}}}Relationship")
        rel.set("Id", rid)
        rel.set("Type", rtype)
        rel.set("Target", posixpath.relpath(target_part, posixpath.dirname(part)))
        self.dirty.add(name)
        return rid

    def ensure_default_type(self, ext: str, ctype: str) -> None:
        root = self.xml("[Content_Types].xml")
        if root is None:
            return
        if any((d.get("Extension") or "").lower() == ext for d in root if etree.QName(d).localname == "Default"):
            return
        d = etree.Element(f"{{{CT}}}Default")
        d.set("Extension", ext)
        d.set("ContentType", ctype)
        root.insert(0, d)
        self.dirty.add("[Content_Types].xml")

    def slide_size(self) -> tuple[int, int]:
        root = self.xml("ppt/presentation.xml")
        sz = root.find(f"{{{P}}}sldSz") if root is not None else None
        if sz is None:
            return 9144000, 5143500
        return int(sz.get("cx")), int(sz.get("cy"))

    def slide_order(self) -> list[str]:
        """Части слайдов в порядке презентации."""
        root = self.xml("ppt/presentation.xml")
        rels = self.rels("ppt/presentation.xml")
        lst = root.find(f"{{{P}}}sldIdLst") if root is not None else None
        out = []
        for sid in lst if lst is not None else []:
            tgt = rels.get(sid.get(f"{{{R}}}id") or "", ("", None))[1]
            if tgt:
                out.append(tgt)
        return out

    def save(self, out: Path | str) -> int:
        """Пишет пакет в `out`; число изменённых и новых частей."""
        changed = {n: etree.tostring(self.trees[n], xml_declaration=True, encoding="UTF-8", standalone=True) for n in self.dirty}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in self.infos:
                zout.writestr(pkgzip.entry(item), changed.get(item.filename, self.data[item.filename]))
            for name, data in self.added.items():
                if name in self.data:
                    continue
                zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                zi.compress_type = pkgzip.compress_type(name)
                zout.writestr(zi, changed.get(name, data))
        Path(out).write_bytes(buf.getvalue())
        return len(changed) + len([n for n in self.added if n not in changed and n not in self.data])


def xfrm_box(xfrm: Optional[etree._Element]) -> Optional[Box]:
    if xfrm is None:
        return None
    off, ext = xfrm.find(f"{{{A}}}off"), xfrm.find(f"{{{A}}}ext")
    if off is None or ext is None:
        return None
    try:
        return float(off.get("x")), float(off.get("y")), float(ext.get("cx")), float(ext.get("cy"))
    except (TypeError, ValueError):
        return None


def shape_box(el: etree._Element) -> Optional[Box]:
    """Рамка верхнеуровневой фигуры (sp, pic, cxnSp, graphicFrame, grpSp) в EMU слайда."""
    tag = etree.QName(el).localname
    if tag in ("sp", "pic", "cxnSp"):
        return xfrm_box(el.find(f"{{{P}}}spPr/{{{A}}}xfrm"))
    if tag == "graphicFrame":
        return xfrm_box(el.find(f"{{{P}}}xfrm"))
    if tag == "grpSp":
        return xfrm_box(el.find(f"{{{P}}}grpSpPr/{{{A}}}xfrm"))
    return None


def overlap(a: Box, b: Box) -> float:
    iw = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return iw * ih
