"""Read-only access to a PPTX package: parts, relationships, slide order, theme, media."""

from __future__ import annotations

import posixpath
import zipfile
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Optional

from lxml import etree

from verstka.analysis.xmlns import NS, REL_BASE, findall, q


@dataclass(frozen=True)
class Rel:
    rid: str
    type: str  # short type, e.g. "slideLayout", "image"
    target: str  # resolved part name (or URL for external)
    external: bool = False


def resolve_target(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))


def rels_part_for(part: str) -> str:
    d, f = posixpath.split(part)
    return posixpath.join(d, "_rels", f + ".rels") if d else posixpath.join("_rels", f + ".rels")


class PptxPackage:
    """Thin zip-backed reader. Keeps parsed XML in memory (templates are a few MB of XML at most)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._zip = zipfile.ZipFile(self.path, "r")
        self._names = set(self._zip.namelist())
        self._xml_cache: dict[str, etree._Element] = {}
        self._rels_cache: dict[str, dict[str, Rel]] = {}

    @classmethod
    def open(cls, path: Path | str) -> "PptxPackage":
        return cls(path)

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> "PptxPackage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- parts ---------------------------------------------------------------
    @property
    def part_names(self) -> list[str]:
        return sorted(self._names)

    def exists(self, part: str) -> bool:
        return part in self._names

    def read(self, part: str) -> bytes:
        return self._zip.read(part)

    def xml(self, part: str) -> etree._Element:
        if part not in self._xml_cache:
            parser = etree.XMLParser(remove_blank_text=False, huge_tree=True)
            self._xml_cache[part] = etree.fromstring(self._zip.read(part), parser)
        return self._xml_cache[part]

    def rels(self, part: str) -> dict[str, Rel]:
        if part in self._rels_cache:
            return self._rels_cache[part]
        rp = rels_part_for(part)
        out: dict[str, Rel] = {}
        if rp in self._names:
            root = self.xml(rp)
            for r in root:
                rid = r.get("Id")
                rtype = (r.get("Type") or "").replace(REL_BASE, "").rsplit("/", 1)[-1]
                target = r.get("Target") or ""
                external = (r.get("TargetMode") or "").lower() == "external"
                out[rid] = Rel(rid=rid, type=rtype, target=target if external else resolve_target(part, target), external=external)
        self._rels_cache[part] = out
        return out

    def rel_targets(self, part: str, rtype: str) -> list[str]:
        return [r.target for r in self.rels(part).values() if r.type == rtype and not r.external]

    def target_of(self, part: str, rid: str) -> Optional[str]:
        r = self.rels(part).get(rid)
        return r.target if r else None

    # ---- presentation ----------------------------------------------------------
    @cached_property
    def presentation(self) -> etree._Element:
        return self.xml("ppt/presentation.xml")

    @cached_property
    def slide_size(self) -> tuple[int, int]:
        sz = self.presentation.find("p:sldSz", NS)
        if sz is None:
            return (9144000, 6858000)
        return (int(sz.get("cx")), int(sz.get("cy")))

    @cached_property
    def slide_parts(self) -> list[str]:
        rels = self.rels("ppt/presentation.xml")
        out: list[str] = []
        lst = self.presentation.find("p:sldIdLst", NS)
        if lst is None:
            return out
        for sld in lst.findall("p:sldId", NS):
            rid = sld.get(q("r:id"))
            rel = rels.get(rid)
            if rel and not rel.external and rel.target in self._names:
                out.append(rel.target)
        return out

    @cached_property
    def master_parts(self) -> list[str]:
        return [t for t in self.rel_targets("ppt/presentation.xml", "slideMaster")]

    def layout_of(self, slide_part: str) -> Optional[str]:
        t = self.rel_targets(slide_part, "slideLayout")
        return t[0] if t else None

    def master_of(self, layout_part: str) -> Optional[str]:
        t = self.rel_targets(layout_part, "slideMaster")
        return t[0] if t else None

    def theme_of(self, master_part: str) -> Optional[str]:
        t = self.rel_targets(master_part, "theme")
        return t[0] if t else None

    def notes_part(self, slide_part: str) -> Optional[str]:
        t = self.rel_targets(slide_part, "notesSlide")
        return t[0] if t else None

    def notes_text(self, slide_part: str) -> str:
        np_ = self.notes_part(slide_part)
        if not np_:
            return ""
        root = self.xml(np_)
        texts = [t.text or "" for t in root.iter(q("a:t"))]
        return "\n".join(s for s in ("".join(texts).split("\n")) if s.strip())

    @cached_property
    def embedded_fonts(self) -> list[str]:
        lst = self.presentation.find("p:embeddedFontLst", NS)
        if lst is None:
            return []
        out = []
        for ef in lst.findall("p:embeddedFont", NS):
            f = ef.find("p:font", NS)
            if f is not None and f.get("typeface"):
                out.append(f.get("typeface"))
        return out

    # ---- media ----------------------------------------------------------------
    def media_bytes(self, part: str) -> bytes:
        return self._zip.read(part)

    def media_parts(self) -> list[str]:
        return [n for n in self.part_names if n.startswith("ppt/media/")]

    def content_type(self, part: str) -> str:
        ct = self.xml("[Content_Types].xml")
        for o in findall(ct, "ct:Override"):
            if (o.get("PartName") or "").lstrip("/") == part:
                return o.get("ContentType") or ""
        ext = part.rsplit(".", 1)[-1].lower()
        for d in findall(ct, "ct:Default"):
            if (d.get("Extension") or "").lower() == ext:
                return d.get("ContentType") or ""
        return ""
