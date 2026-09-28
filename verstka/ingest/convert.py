"""Any presentation file a person calls a template → the .pptx the analysis reads.

A template reaches us in many shapes: a PowerPoint template (.potx), a macro-enabled deck (.pptm, .potm), a slide show
(.ppsx), a theme (.thmx), a legacy binary deck (.ppt, .pot, .pps) or an OpenDocument one (.odp, .otp from LibreOffice
or Google Slides' «Скачать → ODP»). The Office Open XML variants are the same package as a .pptx with another content
type of the main part: they are repackaged byte for byte (macros dropped). A theme keeps its master and layouts under
theme/: it becomes a presentation without slides (the analysis then builds sample slides from the layouts). The binary
and OpenDocument formats are converted by LibreOffice (headless, its own fresh profile).

`sniff` tells what a file is by its bytes, not its name; `to_pptx` returns the .pptx to analyse (the file itself when it
already is one). Errors are ConvertError with a message a person can act on (Russian: it is shown in the UI)."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# what the upload accepts (the web app mirrors this list: web/src/lib/templateFiles.ts)
OOXML_EXTS = (".pptx", ".potx", ".pptm", ".potm", ".ppsx", ".ppsm")
THEME_EXTS = (".thmx",)
LEGACY_EXTS = (".ppt", ".pot", ".pps")
ODF_EXTS = (".odp", ".otp")
ACCEPTED_EXTS = OOXML_EXTS + THEME_EXTS + LEGACY_EXTS + ODF_EXTS

CT_PRESENTATION = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
_MAIN_CT_RE = re.compile(
    r'(<Override\b[^>]*PartName="/ppt/presentation\.xml"[^>]*ContentType=")([^"]+)(")'
    r'|(<Override\b[^>]*ContentType=")([^"]+)("[^>]*PartName="/ppt/presentation\.xml")'
)
_VBA_REL_RE = re.compile(r'<Relationship\b[^>]*Type="[^"]*/vbaProject"[^>]*/>')
_VBA_CT_RE = re.compile(r'<Override\b[^>]*PartName="/ppt/vbaProject\.bin"[^>]*/>|<Default\b[^>]*Extension="bin"[^>]*vbaProject[^>]*/>')
_OLE2_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")

TIMEOUT_S = 180.0


class ConvertError(ValueError):
    """A file that is not a presentation we can read — the message says what to do instead."""


def sniff(path: Path) -> str:
    """«pptx» (any Office Open XML presentation), «thmx», «legacy» (OLE2: .ppt/.pot/.pps), «odp» or a reason it is not a
    presentation: «keynote», «pdf», «word», «excel», «image», «zip», «unknown»."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError:
        return "unknown"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head == _OLE2_MAGIC:
        # a password-protected Office file is an OLE2 container holding the encrypted package
        try:
            with open(path, "rb") as f:
                blob = f.read(4 << 20)
        except OSError:
            blob = b""
        if "EncryptionInfo".encode("utf-16-le") in blob or "EncryptedPackage".encode("utf-16-le") in blob:
            return "encrypted"
        return "legacy"  # .ppt / .pot / .pps (also .doc / .xls — LibreOffice then says it is no presentation)
    if head[:3] == b"\xff\xd8\xff" or head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image"
    if not zipfile.is_zipfile(path):
        return "unknown"
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "ppt/presentation.xml" in names:
                return "pptx"
            if "theme/presentation.xml" in names or "theme/theme/themeManager.xml" in names:
                return "thmx"
            if "mimetype" in names:
                mt = z.read("mimetype").decode("ascii", "ignore").strip()
                if mt.startswith("application/vnd.oasis.opendocument.presentation"):
                    return "odp"
                return "word" if "text" in mt else "excel" if "spreadsheet" in mt else "unknown"
            if any(n.startswith("word/") for n in names):
                return "word"
            if any(n.startswith("xl/") for n in names):
                return "excel"
            if any(n.startswith("Index/") or n.endswith(".iwa") for n in names) or "index.apxl" in names:
                return "keynote"
    except (zipfile.BadZipFile, OSError, KeyError):
        return "unknown"
    return "zip"


_WHY = {
    "pdf": "Это PDF — из него не достать макеты и стили. Нужен файл PowerPoint: .pptx или .potx.",
    "encrypted": "Файл защищён паролем. Снимите пароль в PowerPoint (Файл → Сведения → Защита презентации) и загрузите шаблон снова.",
    "keynote": "Это файл Keynote. Экспортируйте его в PowerPoint (Файл → Экспортировать в → PowerPoint) и загрузите .pptx.",
    "word": "Это документ Word, а нужен шаблон презентации: .pptx, .potx, .ppt или .odp.",
    "excel": "Это таблица Excel, а нужен шаблон презентации: .pptx, .potx, .ppt или .odp.",
    "image": "Это картинка, а нужен шаблон презентации: .pptx, .potx, .ppt или .odp.",
    "zip": "Это архив, а не презентация. Загрузите сам файл шаблона: .pptx, .potx, .ppt или .odp.",
    "unknown": "Файл не похож на презентацию. Загрузите шаблон PowerPoint (.pptx, .potx, .ppt) или OpenDocument (.odp).",
}


def reason(kind: str) -> str:
    return _WHY.get(kind, _WHY["unknown"])


def check_upload(path: Path) -> str:
    """The kind of an uploaded file (sniffed, whatever its name says), or ConvertError with what to upload instead."""
    kind = sniff(path)
    if kind in ("pptx", "thmx", "legacy", "odp"):
        return kind
    raise ConvertError(reason(kind))


def _repackage(src: Path, dst: Path, rename_theme: bool = False) -> Path:
    """Copy an OOXML package into a .pptx: the main part's content type becomes the presentation's, macros are dropped;
    a theme (.thmx) moves theme/* to ppt/* with the presentation-level parts a .pptx carries."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        names = zin.namelist()
        infos = {i.filename: i for i in zin.infolist()}
        if rename_theme:
            _theme_parts(zin, zout, names, infos)
            return dst
        for n in names:
            if n == "ppt/vbaProject.bin" or n.startswith("ppt/vbaProject") or n == "ppt/_rels/vbaProject.bin.rels":
                continue  # macros: never kept (a template needs none)
            data = zin.read(n)
            if n == "[Content_Types].xml":
                s = data.decode("utf-8-sig")
                s = _MAIN_CT_RE.sub(lambda m: (m.group(1) + CT_PRESENTATION + m.group(3)) if m.group(1) else (m.group(4) + CT_PRESENTATION + m.group(6)), s)
                s = _VBA_CT_RE.sub("", s)
                data = s.encode("utf-8")
            elif n == "ppt/_rels/presentation.xml.rels":
                data = _VBA_REL_RE.sub("", data.decode("utf-8-sig")).encode("utf-8")
            zi = zipfile.ZipInfo(n, date_time=infos[n].date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(zi, data)
    return dst


_PRES_PROPS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:presentationPr xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>'
)
_VIEW_PROPS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<p:viewPr xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>'
)
_TABLE_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>'
)


def _theme_parts(zin: zipfile.ZipFile, zout: zipfile.ZipFile, names: list[str], infos: dict) -> None:
    """A .thmx: theme/presentation.xml with its master, layouts, theme and media under theme/ → the same parts under
    ppt/ with a package relationship to the presentation (instead of the theme manager)."""
    skip_prefix = ("themeVariants/",)
    for n in names:
        if n.startswith(skip_prefix) or n in ("[Content_Types].xml", "_rels/.rels"):
            continue
        if n.startswith("theme/theme/themeManager") or n.startswith("theme/theme/_rels/themeManager"):
            continue
        low = n.lower()
        if n.startswith("theme/theme/") and "thumbnail" in low:
            continue
        data = zin.read(n)
        target = "ppt/" + n[len("theme/"):] if n.startswith("theme/") else n
        if target == "ppt/_rels/presentation.xml.rels":
            s = data.decode("utf-8-sig")
            extra = (
                '<Relationship Id="rIdVk1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/presProps" Target="presProps.xml"/>'
                '<Relationship Id="rIdVk2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/viewProps" Target="viewProps.xml"/>'
                '<Relationship Id="rIdVk4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/tableStyles" Target="tableStyles.xml"/>'
            )
            if "/relationships/theme\"" not in s:
                extra += '<Relationship Id="rIdVk3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>'
            data = s.replace("</Relationships>", extra + "</Relationships>").encode("utf-8")
        zi = zipfile.ZipInfo(target, date_time=infos[n].date_time)
        zi.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(zi, data)
    for part, xml in (("ppt/presProps.xml", _PRES_PROPS), ("ppt/viewProps.xml", _VIEW_PROPS), ("ppt/tableStyles.xml", _TABLE_STYLES)):
        if part not in names:
            zout.writestr(part, xml)
    zout.writestr(
        "_rels/.rels",
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
        "</Relationships>",
    )
    ct = zin.read("[Content_Types].xml").decode("utf-8-sig")
    defaults = re.findall(r"<Default\b[^>]+/>", ct)
    overrides = []
    for o in re.findall(r"<Override\b[^>]+/>", ct):
        m = re.search(r'PartName="([^"]+)"', o)
        pn = m.group(1) if m else ""
        if pn.startswith("/themeVariants/") or "themeManager" in pn:
            continue
        if pn.startswith("/theme/"):
            o = o.replace(f'PartName="{pn}"', f'PartName="/ppt/{pn[len("/theme/"):]}"')
        if pn == "/theme/presentation.xml":
            o = re.sub(r'ContentType="[^"]+"', f'ContentType="{CT_PRESENTATION}"', o)
        overrides.append(o)
    overrides += [
        '<Override PartName="/ppt/presProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presProps+xml"/>',
        '<Override PartName="/ppt/viewProps.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml"/>',
        '<Override PartName="/ppt/tableStyles.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"/>',
    ]
    for ext, ctype in (("jpeg", "image/jpeg"), ("jpg", "image/jpeg"), ("png", "image/png"), ("xml", "application/xml"), ("rels", "application/vnd.openxmlformats-package.relationships+xml")):
        if not any(f'Extension="{ext}"' in d for d in defaults):
            defaults.append(f'<Default Extension="{ext}" ContentType="{ctype}"/>')
    zout.writestr(
        "[Content_Types].xml",
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' + "".join(defaults) + "".join(overrides) + "</Types>",
    )


def _needs_repackage(path: Path) -> bool:
    """An Office Open XML presentation whose main part is not the presentation's (a template, a slide show, macros)."""
    try:
        with zipfile.ZipFile(path) as z:
            ct = z.read("[Content_Types].xml").decode("utf-8-sig", "ignore")
            names = set(z.namelist())
    except (zipfile.BadZipFile, KeyError, OSError):
        return False
    m = _MAIN_CT_RE.search(ct)
    main = (m.group(2) or m.group(5)) if m else None
    return (main is not None and main != CT_PRESENTATION) or any(n.startswith("ppt/vbaProject") for n in names)


def _libreoffice(src: Path, out_dir: Path, timeout_s: float = TIMEOUT_S) -> Path:
    from verstka.ingest.render import find_soffice

    soffice = find_soffice()
    if not soffice:
        raise ConvertError("Чтобы открыть этот формат, на сервере нужен LibreOffice. Сохраните шаблон как .pptx и загрузите его.")
    env = os.environ.copy()
    env["SAL_USE_VCLPLUGIN"] = "svp"
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="verstka_conv_", ignore_cleanup_errors=True) as profile:
        cmd = [soffice, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless", "--norestore", "--convert-to", "pptx", "--outdir", str(out_dir), str(src)]
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired as e:
            raise ConvertError("Файл слишком долго открывается. Сохраните шаблон как .pptx и загрузите его.") from e
    out = out_dir / (src.stem + ".pptx")
    if proc.returncode != 0 or not out.exists() or sniff(out) != "pptx":
        log.warning("LibreOffice could not convert %s: rc=%s %s", src.name, proc.returncode, (proc.stderr or "")[-300:])
        raise ConvertError("Не получилось открыть файл: он повреждён или это не презентация. Сохраните шаблон как .pptx и загрузите его.")
    return out


def to_pptx(path: Path, work_dir: Optional[Path] = None) -> Path:
    """The .pptx to analyse for an uploaded template: the file itself when it is a plain .pptx, otherwise a converted
    copy next to it (or in `work_dir`) named after it («Бренд.potx» → «Бренд.pptx»)."""
    path = Path(path)
    kind = check_upload(path)
    out_dir = Path(work_dir) if work_dir else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = path.stem or "template"
    if kind == "pptx":
        if not _needs_repackage(path) and path.suffix.lower() == ".pptx":
            return path
        dst = out_dir / f"{stem}.pptx"
        if dst == path:
            dst = out_dir / f"{stem}-converted.pptx"
        return _repackage(path, dst)
    if kind == "thmx":
        dst = out_dir / f"{stem}.pptx"
        return _repackage(path, dst, rename_theme=True)
    # legacy binary / OpenDocument → LibreOffice
    with tempfile.TemporaryDirectory(prefix="verstka_in_", ignore_cleanup_errors=True) as tmp:
        # LibreOffice picks the filter by the extension: give it the one the bytes say
        ext = {"legacy": ".ppt", "odp": ".odp"}[kind]
        src = Path(tmp) / f"{stem}{ext}"
        shutil.copyfile(path, src)
        got = _libreoffice(src, Path(tmp) / "out")
        dst = out_dir / f"{stem}.pptx"
        if dst == path:
            dst = out_dir / f"{stem}-converted.pptx"
        shutil.move(str(got), dst)
    return dst
