"""Writing a .pptx package without deflating its pictures again.

python-pptx deflates every part at every save. A template's pictures are PNG and JPEG, compressed already: deflating
them again gains nothing and cost LCT (four 4.7 MB backgrounds) seven seconds a generation — a deck is saved and
rewritten several times (render, the Cyrillic passes, autofix). Pictures, video and sound are stored as they are; the
XML parts stay deflated. `rewrite` replaces parts of a package keeping every other entry's own compression.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

STORED_EXT = (".png", ".jpg", ".jpeg", ".jfif", ".gif", ".webp", ".wdp", ".mp4", ".m4v", ".mov", ".mp3", ".m4a")


def compress_type(name: str) -> int:
    """How a package part is written: stored for media compressed by their own format, deflated otherwise."""
    return zipfile.ZIP_STORED if name.lower().endswith(STORED_EXT) else zipfile.ZIP_DEFLATED


def entry(item: zipfile.ZipInfo) -> zipfile.ZipInfo:
    """A new entry for `item` in a package being written, compressed by `compress_type` (a picture deflated by the
    template's editor is stored from then on). A copy: `ZipFile.writestr` fills in the entry it is given, and the
    reader still reads the old package through `item`."""
    out = zipfile.ZipInfo(item.filename, date_time=item.date_time)
    out.compress_type = compress_type(item.filename)
    out.external_attr = item.external_attr
    return out


def rewrite(path: Path | str, changed: dict[str, bytes]) -> None:
    """The package at `path` with the parts of `changed` replaced (in place); nothing is written when nothing changed."""
    if not changed:
        return
    path = Path(path)
    buf = io.BytesIO()
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = changed.get(item.filename)
            zout.writestr(entry(item), zin.read(item) if data is None else data)
    path.write_bytes(buf.getvalue())


def install() -> None:
    """python-pptx saves through `compress_type` too."""
    from pptx.opc import serialized

    if getattr(serialized._ZipPkgWriter.write, "_verstka", False):
        return

    def write(self, pack_uri, blob: bytes) -> None:
        name = pack_uri.membername
        self._zipf.writestr(name, blob, compress_type=compress_type(name))

    write._verstka = True  # type: ignore[attr-defined]
    serialized._ZipPkgWriter.write = write
