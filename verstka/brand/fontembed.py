"""Шрифты внутри PPTX (ECMA-376, ч. 1, §13.3.? «Font Part», PresentationML `p:embeddedFontLst`).

Подобранные Verstka шрифты (Manrope, Literata, Unbounded… — `verstka/fonts/<семейство>/`, OFL) есть не у всех: колода,
открытая у жюри в PowerPoint без них, набралась бы Arial. Поэтому их файлы кладутся в саму колоду — так, как это делает
PowerPoint при «Внедрить шрифты»:

- часть `ppt/fonts/fontN.fntdata` (тип содержимого `application/x-fontdata`) — шрифт в обёртке Embedded OpenType
  (EOT, версия 0x00020001, без сжатия и без XOR-обфускации: формат, который PowerPoint и LibreOffice читают);
- связь `…/relationships/font` из `ppt/presentation.xml`;
- `p:embeddedFontLst/p:embeddedFont` с `p:font typeface=…` и начертаниями `p:regular`, `p:bold`;
- `p:presentation/@embedTrueTypeFonts="1"`.

LibreOffice (импорт PPTX) извлекает такие шрифты и набирает ими превью и PDF — и на macOS, где ему нельзя указать
папку со шрифтами. Шрифты OFL разрешают встраивание (OS/2 fsType = 0); шрифт с запретом встраивания не кладётся.
"""

from __future__ import annotations

import logging
import re
import struct
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from lxml import etree

from verstka import pkgzip

log = logging.getLogger(__name__)

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
FONT_REL = R + "/font"
FONT_CT = "application/x-fontdata"
FONT_DIR = Path(__file__).resolve().parents[1] / "fonts"

# порядок детей p:presentation (CT_Presentation): список шрифтов стоит после размеров слайдов и заметок
_AFTER_FONTS = ("custShowLst", "photoAlbum", "custDataLst", "kinsoku", "defaultTextStyle", "modifyVerifier", "extLst")


# ============================================================================================ шрифты Verstka


def _tables(data: bytes) -> dict[bytes, tuple[int, int]]:
    """Таблицы TrueType/OpenType: тег → (смещение, длина)."""
    n = struct.unpack(">H", data[4:6])[0]
    out = {}
    for i in range(n):
        tag, _cs, off, ln = struct.unpack(">4sIII", data[12 + 16 * i : 28 + 16 * i])
        out[tag] = (off, ln)
    return out


def _names(data: bytes, tables: dict) -> dict[int, str]:
    """Имена из таблицы `name` (Windows, Unicode, английский — первым; иначе Mac Roman)."""
    off, _ = tables[b"name"]
    _fmt, count, sto = struct.unpack(">HHH", data[off : off + 6])
    win: dict[int, str] = {}
    mac: dict[int, str] = {}
    for i in range(count):
        pid, eid, lid, nid, ln, so = struct.unpack(">HHHHHH", data[off + 6 + 12 * i : off + 18 + 12 * i])
        raw = data[off + sto + so : off + sto + so + ln]
        if pid == 3 and eid in (0, 1, 10):
            if lid == 0x409 or nid not in win:
                win[nid] = raw.decode("utf-16-be", "replace")
        elif pid == 1 and eid == 0 and nid not in mac:
            mac[nid] = raw.decode("mac_roman", "replace")
    return {**mac, **win}


class FontFile:
    """Файл шрифта и то, что нужно знать о нём для EOT и `p:embeddedFont`."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.data = self.path.read_bytes()
        t = _tables(self.data)
        names = _names(self.data, t)
        self.family = names.get(16) or names.get(1) or self.path.stem
        self.style = names.get(17) or names.get(2) or "Regular"
        self.version = names.get(5) or ""
        self.full = names.get(4) or f"{self.family} {self.style}"
        o, _ = t[b"OS/2"]
        os2 = self.data[o : o + 96]
        self.weight = struct.unpack(">H", os2[4:6])[0]
        self.fs_type = struct.unpack(">H", os2[8:10])[0]
        self.panose = os2[32:42]
        self.unicode_ranges = struct.unpack(">IIII", os2[42:58])
        self.fs_selection = struct.unpack(">H", os2[62:64])[0]
        self.code_pages = struct.unpack(">II", os2[78:86]) if len(os2) >= 86 else (0, 0)
        h, _ = t[b"head"]
        self.checksum_adjustment = struct.unpack(">I", self.data[h + 8 : h + 12])[0]
        mac_style = struct.unpack(">H", self.data[h + 44 : h + 46])[0]
        self.bold = bool(self.fs_selection & 0x20) or bool(mac_style & 1)
        self.italic = bool(self.fs_selection & 0x1) or bool(mac_style & 2)

    @property
    def embeddable(self) -> bool:
        """OS/2 fsType: 0 — без ограничений; бит 1 (0x2) — встраивание запрещено; бит 9 (0x200) — только картинкой."""
        return not (self.fs_type & 0x0002) and not (self.fs_type & 0x0200)

    def eot(self) -> bytes:
        """Шрифт в обёртке EOT 0x00020001 (без сжатия, без XOR) — содержимое части `.fntdata`."""

        def name(s: str) -> bytes:
            b = s.encode("utf-16-le")
            return struct.pack("<H", len(b)) + b

        head = struct.pack("<I", 0x00020001) + struct.pack("<I", 0)  # Version, Flags
        head += self.panose + struct.pack("<BBIHH", 1, 1 if self.italic else 0, self.weight, self.fs_type, 0x504C)
        head += struct.pack("<IIII", *self.unicode_ranges) + struct.pack("<II", *self.code_pages)
        head += struct.pack("<I", self.checksum_adjustment) + b"\0" * 16
        body = struct.pack("<H", 0) + name(self.family)
        body += struct.pack("<H", 0) + name(self.style)
        body += struct.pack("<H", 0) + name(self.version)
        body += struct.pack("<H", 0) + name(self.full)
        body += struct.pack("<H", 0) + struct.pack("<H", 0)  # Padding5, RootStringSize = 0
        size = 8 + len(head) + len(body) + len(self.data)
        return struct.pack("<II", size, len(self.data)) + head + body + self.data


@lru_cache(maxsize=1)
def bundled_fonts() -> dict[str, dict[str, Path]]:
    """Шрифты Verstka (`verstka/fonts/**`): семейство (как в `a:latin`) → {regular, bold: файл}."""
    out: dict[str, dict[str, Path]] = {}
    if not FONT_DIR.is_dir():
        return out
    for p in sorted(FONT_DIR.rglob("*.[ot]tf")):
        try:
            ff = FontFile(p)
        except Exception:  # noqa: BLE001 - битый файл пропускается
            continue
        if ff.italic:
            continue
        out.setdefault(ff.family, {})["bold" if ff.bold else "regular"] = p
    return out


def bundled_family(name: Optional[str]) -> Optional[str]:
    """Имя семейства Verstka, совпадающее с `name` без учёта регистра и пробелов, или None."""
    key = re.sub(r"[\s_\-]+", "", (name or "").lower())
    return next((f for f in bundled_fonts() if re.sub(r"[\s_\-]+", "", f.lower()) == key), None) if key else None


SIGNS = "→₽№×"  # знаки колод Verstka: «61 → 35», «900 ₽», «№ 3», «×2»


@lru_cache(maxsize=64)
def figures_report(family: str) -> tuple[bool, str]:
    """(цифры выравненные — одной высоты, на линии шрифта; знаки из `SIGNS`, которых в шрифте нет) для шрифта Verstka.
    Старостильные цифры («1 240» прыгает по высоте) и стрелка из запасного шрифта портят KPI и таблицы."""
    from PIL import ImageFont

    path = (bundled_fonts().get(family) or {}).get("regular")
    if path is None:
        return False, SIGNS
    f = ImageFont.truetype(str(path), 200)
    cmap_missing = "".join(ch for ch in SIGNS if not _maps(path, ch))
    tops, bottoms = [], []
    for d in "0123456789":
        bb = f.getbbox(d, anchor="ls")
        tops.append(bb[1])
        bottoms.append(bb[3])
    cap = -f.getbbox("H", anchor="ls")[1]
    lining = (max(tops) - min(tops)) < 0.08 * cap and max(bottoms) < 0.05 * cap
    return lining, cmap_missing


def _maps(path: Path, ch: str) -> bool:
    """Шрифт сам рисует `ch` (cmap), а не «.notdef»."""
    data = path.read_bytes()
    t = _tables(data)
    off, _ = t[b"cmap"]
    n = struct.unpack(">H", data[off + 2 : off + 4])[0]
    cp = ord(ch)
    for i in range(n):
        pid, eid, sub = struct.unpack(">HHI", data[off + 4 + 8 * i : off + 12 + 8 * i])
        so = off + sub
        fmt = struct.unpack(">H", data[so : so + 2])[0]
        if fmt == 4 and cp <= 0xFFFF:
            segx2 = struct.unpack(">H", data[so + 6 : so + 8])[0]
            ends = struct.unpack(f">{segx2 // 2}H", data[so + 14 : so + 14 + segx2])
            starts = struct.unpack(f">{segx2 // 2}H", data[so + 16 + segx2 : so + 16 + 2 * segx2])
            if any(st <= cp <= en for st, en in zip(starts, ends) if en != 0xFFFF or st != 0xFFFF):
                return True
        elif fmt == 12:
            ng = struct.unpack(">I", data[so + 12 : so + 16])[0]
            for g in range(ng):
                st, en, _ = struct.unpack(">III", data[so + 16 + 12 * g : so + 28 + 12 * g])
                if st <= cp <= en:
                    return True
    return False


# ============================================================================================ встраивание


def _ensure_default(ct_root: etree._Element, ext: str, ctype: str) -> bool:
    if any((d.get("Extension") or "").lower() == ext for d in ct_root if etree.QName(d).localname == "Default"):
        return False
    d = etree.Element(f"{{{CT}}}Default")
    d.set("Extension", ext)
    d.set("ContentType", ctype)
    ct_root.insert(0, d)
    return True


def used_families(pptx: Path | str) -> set[str]:
    """Семейства, которые называют `a:latin` / `a:ea` / `a:cs` слайдов, макетов, мастеров, тем и диаграмм."""
    rx = re.compile(rb"<a:(?:latin|ea|cs)\b[^>]*?\btypeface=\"([^\"]+)\"")
    out: set[str] = set()
    with zipfile.ZipFile(pptx) as z:
        for n in z.namelist():
            if n.startswith("ppt/") and n.endswith(".xml") and not n.startswith("ppt/notesSlides/"):
                out.update(m.group(1).decode("utf-8", "replace") for m in rx.finditer(z.read(n)))
    return out


def embedded_families(pptx: Path | str) -> list[str]:
    """Семейства в `p:embeddedFontLst` колоды."""
    with zipfile.ZipFile(pptx) as z:
        pres = z.read("ppt/presentation.xml")
    return [m.decode("utf-8", "replace") for m in re.findall(rb"<p:embeddedFont>\s*<p:font\b[^>]*?\btypeface=\"([^\"]+)\"", pres)]


def embed_fonts(pptx: Path | str, families: Optional[Iterable[str]] = None) -> list[str]:
    """Кладёт в колоду (на месте) шрифты Verstka, которыми она набрана (или `families`), — обычное и полужирное
    начертания. Уже встроенное семейство не дублируется. Возвращает встроенные сейчас семейства."""
    pptx = Path(pptx)
    want = families if families is not None else used_families(pptx)
    fams = sorted({f for f in (bundled_family(x) for x in want) if f})  # порядок не зависит от порядка частей
    if not fams:
        return []
    have = {x.lower() for x in embedded_families(pptx)}
    fams = [f for f in fams if f.lower() not in have]
    if not fams:
        return []
    with zipfile.ZipFile(pptx) as z:
        names = set(z.namelist())
        pres = etree.fromstring(z.read("ppt/presentation.xml"))
        rels_name = "ppt/_rels/presentation.xml.rels"
        rels = etree.fromstring(z.read(rels_name)) if rels_name in names else etree.Element(f"{{{PR}}}Relationships", nsmap={None: PR})
        ct = etree.fromstring(z.read("[Content_Types].xml"))
    changed: dict[str, bytes] = {}
    added: dict[str, bytes] = {}
    ids = {r.get("Id") for r in rels}
    n_font = 1

    def new_part(data: bytes) -> str:
        nonlocal n_font
        while f"ppt/fonts/font{n_font}.fntdata" in names or f"ppt/fonts/font{n_font}.fntdata" in added:
            n_font += 1
        part = f"ppt/fonts/font{n_font}.fntdata"
        added[part] = data
        k = 1
        while f"rIdFont{k}" in ids:
            k += 1
        rid = f"rIdFont{k}"
        ids.add(rid)
        rel = etree.SubElement(rels, f"{{{PR}}}Relationship")
        rel.set("Id", rid)
        rel.set("Type", FONT_REL)
        rel.set("Target", part[len("ppt/") :])
        return rid

    lst = pres.find(f"{{{P}}}embeddedFontLst")
    if lst is None:
        lst = etree.Element(f"{{{P}}}embeddedFontLst")
        anchor = next((pres.find(f"{{{P}}}{t}") for t in _AFTER_FONTS if pres.find(f"{{{P}}}{t}") is not None), None)
        if anchor is not None:
            anchor.addprevious(lst)
        else:
            pres.append(lst)
    done: list[str] = []
    for fam in fams:
        faces = bundled_fonts().get(fam) or {}
        files = {k: FontFile(v) for k, v in faces.items()}
        files = {k: f for k, f in files.items() if f.embeddable}
        if "regular" not in files:
            continue
        ef = etree.SubElement(lst, f"{{{P}}}embeddedFont")
        fe = etree.SubElement(ef, f"{{{P}}}font")
        fe.set("typeface", fam)
        panose = files["regular"].panose
        fe.set("panose", panose.hex().upper())
        # pitchFamily: переменная ширина (2) + семейство по PANOSE (антиква — roman 0x10, гротеск — swiss 0x20)
        serif = panose[0] == 2 and panose[1] in range(2, 11)
        fe.set("pitchFamily", "18" if serif else "34")
        fe.set("charset", "0")
        for kind in ("regular", "bold"):
            if kind in files:
                etree.SubElement(ef, f"{{{P}}}{kind}").set(f"{{{R}}}id", new_part(files[kind].eot()))
        done.append(fam)
    if not done:
        return []
    pres.set("embedTrueTypeFonts", "1")
    changed["ppt/presentation.xml"] = etree.tostring(pres, xml_declaration=True, encoding="UTF-8", standalone=True)
    changed[rels_name] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True)
    _ensure_default(ct, "fntdata", FONT_CT)
    changed["[Content_Types].xml"] = etree.tostring(ct, xml_declaration=True, encoding="UTF-8", standalone=True)
    _write(pptx, changed, added)
    return done


def _write(path: Path, changed: dict[str, bytes], added: dict[str, bytes]) -> None:
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = changed.get(item.filename)
            zout.writestr(pkgzip.entry(item), zin.read(item) if data is None else data)
        for name, data in added.items():
            zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(zi, data)
    path.write_bytes(buf.getvalue())
