"""Russian text in a template's fonts: a family without Cyrillic sets its Latin letters and leaves every Russian
letter to whatever fallback the viewer has — two faces inside one word. Free templates are full of such families
(Google Fonts: DM Sans, Lato, Barlow, Cabin, Anton, Cardo, Libre Baskerville…), often embedded in the file.

`cyrillic_substitutes(source)` tells, for every family the template names, whether it covers Cyrillic — by the
embedded font's own header (EOT: its OS/2 Unicode ranges and code pages, and whether it is a subset), else by the face
installed on this machine, else by a table of well-known families — and picks a stand-in for each one that does not:
a family of the same class the template itself uses with Cyrillic (its Inter beside a Latin-only Cardo…), else a
cross-platform face every PowerPoint has (Arial, Georgia, Impact, Arial Narrow, Courier New). `deck_fonts(subs)` makes
the measuring (fonts.text_width_pt) use the stand-ins while a deck is rendered; `apply_to_pptx(path, subs)` writes them
into the finished file wherever the deck's own text is set (Russian words, figures): the runs and paragraph defaults that hold it, the text styles of
masters and layouts, the theme's heading and body fonts. Latin text the template keeps (a logo word, a footer) keeps
its own face."""

from __future__ import annotations

import contextlib
import contextvars
import io
import logging
import re
import struct
import zipfile
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger(__name__)

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
CYR_RE = re.compile(r"[А-Яа-яЁё]")
LAT_RE = re.compile(r"[A-Za-z]")

# well-known families without Cyrillic (Google Fonts as served, Office and Apple faces) — used when neither the file nor
# this machine can tell
LATIN_ONLY = frozenset(
    x.lower()
    for x in (
        "Poppins", "DM Sans", "DM Serif Display", "DM Serif Text", "DM Mono", "Lato", "Barlow", "Barlow Condensed",
        "Barlow Semi Condensed", "Cabin", "Cabin Condensed", "Public Sans", "Cardo", "Libre Baskerville", "Libre Franklin",
        "Alata", "Anton", "Bebas Neue", "League Spartan", "League Gothic", "Outfit", "Sora", "Syne", "Work Sans", "Karla",
        "Space Grotesk", "Space Mono", "Bricolage Grotesque", "Inclusive Sans", "Amiko", "Cinzel", "Cinzel Decorative",
        "Abril Fatface", "Archivo", "Archivo Black", "Archivo Narrow", "Chivo", "Epilogue", "Red Hat Display", "Red Hat Text",
        "Titillium Web", "Hind", "Mukta", "Heebo", "Assistant", "Arvo", "Righteous", "Fredoka", "Fredoka One", "Quicksand",
        "Josefin Sans", "Josefin Slab", "Plus Jakarta Sans", "Be Vietnam Pro", "Lexend", "Urbanist", "Kanit", "Prompt",
        "Montserrat Alternates", "Zilla Slab", "Crimson Text", "Nanum Myeongjo", "Nanum Gothic", "Gilda Display",
        "Bodoni Moda", "Gloock", "Instrument Serif", "Instrument Sans", "Hanken Grotesk", "Schibsted Grotesk",
        "Gill Sans MT", "Gill Sans", "Tw Cen MT", "Tw Cen MT Condensed", "Century Gothic", "Rockwell", "Goudy Old Style",
        "Perpetua", "Futura", "Avenir", "Optima", "Didot", "Bodoni 72", "American Typewriter", "Chalkboard",
        "Gill Sans Nova", "Avenir Next LT Pro", "Segoe Print", "Segoe Script",
    )
)
# well-known families that cover Cyrillic
CYRILLIC_OK = frozenset(
    x.lower()
    for x in (
        "Arial", "Arial Narrow", "Arial Black", "Helvetica", "Helvetica Neue", "Times New Roman", "Times", "Georgia", "Verdana",
        "Tahoma", "Trebuchet MS", "Calibri", "Calibri Light", "Cambria", "Candara", "Corbel", "Constantia", "Consolas",
        "Courier New", "Segoe UI", "Segoe UI Light", "Segoe UI Semibold", "Impact", "Franklin Gothic Medium", "Garamond",
        "Palatino Linotype", "Book Antiqua", "Aptos", "Aptos Display", "Montserrat", "Roboto", "Open Sans", "Inter", "Noto Sans",
        "Noto Serif", "PT Sans", "PT Serif", "PT Sans Narrow", "Source Sans Pro", "Source Sans 3", "Source Serif Pro",
        "IBM Plex Sans", "IBM Plex Serif", "IBM Plex Mono", "Merriweather", "Merriweather Sans", "Lora", "Rubik", "Fira Sans",
        "Exo 2", "Ubuntu", "Comfortaa", "Jost", "Spectral", "EB Garamond", "Cormorant", "Cormorant Garamond", "Prata",
        "Old Standard TT", "Tenor Sans", "Forum", "Marck Script", "Caveat", "Amatic SC", "Poiret One", "Yeseva One",
        "Russo One", "Play", "Golos Text", "Onest", "Unbounded", "Manrope", "Commissioner", "Arimo", "Tinos", "Cousine",
        "Alegreya", "Alegreya Sans", "Alegreya Sans SC", "Roboto Slab", "Roboto Condensed", "Roboto Mono", "Bitter", "Oswald",
        "Playfair Display", "Raleway", "Nunito", "Mulish", "Pacifico", "Great Vibes", "Philosopher", "Didact Gothic",
        "Istok Web", "Scada", "Arsenal", "Ledger", "Literata", "Carlito", "Caladea", "Liberation Sans", "Liberation Serif",
        "DejaVu Sans", "VK Sans", "VK Sans Display", "Inter Tight", "Geologica", "Wix Madefor Text", "Wix Madefor Display",
    )
)
# cross-platform faces with Cyrillic every PowerPoint has, per class
SAFE = {
    "sans": "Arial",
    "serif": "Georgia",
    "display_condensed": "Impact",
    "condensed": "Arial Narrow",
    "mono": "Courier New",
}
_WEIGHT_TAIL_RE = re.compile(
    r"[\s\-_]+(?:regular|book|roman|normal|thin|hairline|extra ?light|ultra ?light|light|medium|semi ?bold|demi ?bold|demi|"
    r"extra ?bold|ultra ?bold|bold|heavy|black|italic|oblique)$",
    re.I,
)


def base_family(name: str) -> str:
    """«Inter Light» → «inter», «Montserrat-Regular» → «montserrat»."""
    n = (name or "").strip().lower()
    while True:
        cut = _WEIGHT_TAIL_RE.sub("", n)
        if cut == n or not cut:
            return n
        n = cut


# ---------------------------------------------------------------------------------------------- the file's own fonts


def _eot_cyrillic(data: bytes) -> Optional[bool]:
    """Whether an embedded font (EOT, as PowerPoint and Google Slides embed them) covers Cyrillic: its OS/2 Unicode
    range bit 9 or code page 1251, and not a subset (a subset keeps only the characters the template used)."""
    if len(data) < 60:
        return None
    try:
        flags = struct.unpack("<I", data[12:16])[0]
        magic = struct.unpack("<H", data[34:36])[0]
        if magic != 0x504C:
            return None
        ur1 = struct.unpack("<I", data[36:40])[0]
        cp1 = struct.unpack("<I", data[52:56])[0]
    except struct.error:
        return None
    if flags & 0x1:
        return False  # a subset: the template's own (Latin) characters only
    return bool(ur1 & (1 << 9)) or bool(cp1 & (1 << 2))


def embedded_coverage(pptx: Path | str) -> dict[str, bool]:
    """{base family: covers Cyrillic} for the fonts embedded in the package (every face of a family must cover it)."""
    out: dict[str, bool] = {}
    try:
        with zipfile.ZipFile(pptx) as z:
            names = set(z.namelist())
            if "ppt/presentation.xml" not in names:
                return out
            pres = z.read("ppt/presentation.xml").decode("utf-8", "ignore")
            rels = z.read("ppt/_rels/presentation.xml.rels").decode("utf-8", "ignore") if "ppt/_rels/presentation.xml.rels" in names else ""
            for m in re.finditer(r"<p:embeddedFont>\s*<p:font\s+typeface=\"([^\"]+)\"[^>]*/>(.*?)</p:embeddedFont>", pres, re.S):
                fam = base_family(m.group(1))
                for rid in re.findall(r"r:id=\"([^\"]+)\"", m.group(2)):
                    t = re.search(r"<Relationship\b[^>]*\bId=\"%s\"[^>]*\bTarget=\"([^\"]+)\"" % re.escape(rid), rels) or re.search(
                        r"<Relationship\b[^>]*\bTarget=\"([^\"]+)\"[^>]*\bId=\"%s\"" % re.escape(rid), rels
                    )
                    if not t:
                        continue
                    part = "ppt/" + t.group(1).lstrip("/").replace("../", "") if not t.group(1).startswith("/") else t.group(1).lstrip("/")
                    if part not in names:
                        continue
                    ok = _eot_cyrillic(z.read(part))
                    if ok is None:
                        continue
                    out[fam] = out.get(fam, True) and ok
    except (zipfile.BadZipFile, OSError, KeyError):
        pass
    return out


def supports_cyrillic(family: str, embedded: Optional[dict[str, bool]] = None) -> Optional[bool]:
    """True / False / None (unknown) for a family name the template uses."""
    from verstka.rendering.fonts import _SYMBOL_RE

    name = (family or "").strip()
    if not name or name.startswith("+") or _SYMBOL_RE.search(name):
        return None  # a symbol font (Wingdings, Symbol) draws marks, never letters: it has no stand-in
    base = base_family(name)
    if embedded and base in embedded:
        return embedded[base]
    try:
        from verstka.rendering.fonts import _has_glyph, _installed_face

        face = _installed_face(name) or (_installed_face(base) if base != name.lower() else None)
        if face is not None:
            return _has_glyph(face, "ж")
    except Exception:  # noqa: BLE001 - the tables decide
        pass
    if base in LATIN_ONLY or name.lower() in LATIN_ONLY:
        return False
    if base in CYRILLIC_OK or name.lower() in CYRILLIC_OK:
        return True
    return None


# ---------------------------------------------------------------------------------------------- the stand-ins


def _families_in(pptx: Path | str) -> tuple[list[str], dict[str, int]]:
    """Every font family the package names (runs, styles, themes), and how often its slides set text in each (the
    designer's own families: masters, layouts and themes of exported decks name Calibri and Arial by default)."""
    from collections import Counter

    seen: Counter = Counter()
    on_slides: Counter = Counter()
    try:
        with zipfile.ZipFile(pptx) as z:
            for n in z.namelist():
                if not (n.endswith(".xml") and (n.startswith("ppt/slides/") or n.startswith("ppt/slideLayouts/") or n.startswith("ppt/slideMasters/") or n.startswith("ppt/theme/"))):
                    continue
                for fam in re.findall(r"<a:latin\b[^>]*\btypeface=\"([^\"]+)\"", z.read(n).decode("utf-8", "ignore")):
                    if fam and not fam.startswith("+"):
                        seen[fam] += 1
                        if n.startswith("ppt/slides/"):
                            on_slides[fam] += 1
    except (zipfile.BadZipFile, OSError):
        pass
    return [f for f, _ in seen.most_common()], dict(on_slides)


def cyrillic_substitutes(pptx: Path | str, extra: Iterable[str] = ()) -> dict[str, str]:
    """{family without Cyrillic: its stand-in} for the template at `pptx` (and `extra` families, the analysis's)."""
    from verstka.rendering.fonts import font_class

    embedded = embedded_coverage(pptx)
    named, on_slides = _families_in(pptx)
    fams = list(dict.fromkeys([*named, *[f for f in extra if f]]))
    verdict = {f: supports_cyrillic(f, embedded) for f in fams}
    # the template's own families with Cyrillic, by class: the ones the designer embedded first, then the ones its
    # slides set most text in — the stand-in keeps the template's design (its Inter beside a Latin-only Cardo)
    own: dict[str, str] = {}
    ranked = sorted((f for f in fams if verdict.get(f) and not f.startswith("+")), key=lambda f: (base_family(f) not in embedded, -on_slides.get(f, 0)))
    for f in ranked:
        own.setdefault(font_class(f), f)
    out: dict[str, str] = {}
    for f in fams:
        if verdict.get(f) is not False:
            continue
        cls = font_class(f)
        cand = own.get(cls)
        if cand is None and cls in ("display_condensed", "condensed"):
            cand = own.get("condensed") or own.get("display_condensed")
        out[f] = cand or SAFE.get(cls, "Arial")
    return out


# ---------------------------------------------------------------------------------------------- measuring and writing

_SUBS: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar("verstka_cyrillic_subs", default={})


@contextlib.contextmanager
def deck_fonts(subs: dict[str, str]):
    """While a deck is rendered, text set in a family without Cyrillic is measured in its stand-in."""
    token = _SUBS.set({k.strip().lower(): v for k, v in (subs or {}).items()})
    try:
        yield
    finally:
        _SUBS.reset(token)


def measured_family(family: Optional[str]) -> Optional[str]:
    """The family a text set in `family` is measured in (its stand-in while `deck_fonts` is on)."""
    subs = _SUBS.get()
    if not subs or not family:
        return family
    return subs.get(family.strip().lower(), family)


def _swap(el, subs: dict[str, str]) -> bool:
    lat = el.find(f"{{{_A}}}latin")
    if lat is None:
        return False
    tf = lat.get("typeface") or ""
    new = subs.get(tf.strip().lower())
    if new and new != tf:
        lat.set("typeface", new)
        return True
    return False


def _fix_part(xml: bytes, subs: dict[str, str], whole: bool) -> Optional[bytes]:
    """Stand-ins in one part: `whole` (masters' and layouts' text styles, themes) every latin typeface; else only the
    runs, paragraph defaults and list styles of shapes that hold Russian text."""
    from lxml import etree

    try:
        root = etree.fromstring(xml)
    except etree.XMLSyntaxError:
        return None
    changed = False
    if whole:
        for lat in root.iter(f"{{{_A}}}latin"):
            tf = lat.get("typeface") or ""
            new = subs.get(tf.strip().lower())
            if new and new != tf:
                lat.set("typeface", new)
                changed = True
        # a master's or layout's placeholders and text styles keep their families for Latin text only when no
        # Russian text inherits them — every placeholder of a composed deck holds Russian text
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True) if changed else None
    for body in root.iter(f"{{{_A}}}txBody", f"{{{_P}}}txBody"):
        text = "".join(t.text or "" for t in body.iter(f"{{{_A}}}t"))
        if not text.strip() or (LAT_RE.search(text) and not CYR_RE.search(text)):
            continue  # Latin words the template keeps (a brand, a footer) keep their face; figures are the deck's own
        for tag in ("rPr", "defRPr", "endParaRPr"):
            for rpr in body.iter(f"{{{_A}}}{tag}"):
                changed |= _swap(rpr, subs)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True) if changed else None


def _mark_part(xml: bytes) -> Optional[bytes]:
    from lxml import etree

    try:
        root = etree.fromstring(xml)
    except etree.XMLSyntaxError:
        return None
    changed = False
    for r in root.iter(f"{{{_A}}}r"):
        t = r.find(f"{{{_A}}}t")
        if t is None or not CYR_RE.search(t.text or ""):
            continue
        rpr = r.find(f"{{{_A}}}rPr")
        if rpr is None:
            rpr = etree.Element(f"{{{_A}}}rPr")
            r.insert(0, rpr)
        if rpr.get("lang") != "ru-RU":
            rpr.set("lang", "ru-RU")
            changed = True
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True) if changed else None


def _unhighlight_part(xml: bytes) -> Optional[bytes]:
    if b"highlight" not in xml:
        return None
    from lxml import etree

    try:
        root = etree.fromstring(xml)
    except etree.XMLSyntaxError:
        return None
    gone = [h for h in root.iter(f"{{{_A}}}highlight")]
    for h in gone:
        h.getparent().remove(h)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True) if gone else None


def strip_highlights(pptx: Path | str) -> int:
    """Text highlights taken off a finished deck (in place) — slides, layouts, masters: a LibreOffice template carries
    its character background as a highlight in its text styles (white under the white subtitle of «Piano»), and the
    deck's own words written in that style disappear. Returns the number of parts changed."""
    path = Path(pptx)
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            name = item.filename
            if name.endswith(".xml") and (name.startswith("ppt/slides/slide") or name.startswith("ppt/slideLayouts/") or name.startswith("ppt/slideMasters/")):
                got = _unhighlight_part(data)
                if got is not None:
                    data = got
                    n += 1
            zout.writestr(item, data)
    if n:
        path.write_bytes(buf.getvalue())
    return n


def mark_russian(pptx: Path | str) -> int:
    """Russian runs of a finished deck (in place) tagged `lang="ru-RU"`: a run keeps the language of the template's
    sample it was written into («en-US» in most free templates), and PowerPoint underlines every Russian word of such
    a run as misspelled. Returns the number of parts changed."""
    path = Path(pptx)
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            name = item.filename
            if name.endswith(".xml") and (name.startswith("ppt/slides/slide") or name.startswith("ppt/notesSlides/")):
                got = _mark_part(data)
                if got is not None:
                    data = got
                    n += 1
            zout.writestr(item, data)
    if n:
        path.write_bytes(buf.getvalue())
    return n


def apply_to_pptx(pptx: Path | str, subs: dict[str, str]) -> int:
    """Write the stand-ins into a finished deck (in place). Returns the number of parts changed."""
    if not subs:
        return 0
    low = {k.strip().lower(): v for k, v in subs.items()}
    path = Path(pptx)
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            name = item.filename
            if name.endswith(".xml") and (name.startswith("ppt/slides/slide") or name.startswith("ppt/notesSlides/")):
                got = _fix_part(data, low, whole=False)
            elif name.endswith(".xml") and (
                name.startswith("ppt/slideMasters/") or name.startswith("ppt/slideLayouts/") or name.startswith("ppt/theme/") or name.startswith("ppt/charts/chart")
            ):
                # charts: every label is the deck's own (Russian) text
                got = _fix_part(data, low, whole=True)
            else:
                got = None
            if got is not None:
                data = got
                n += 1
            zout.writestr(item, data)
    if n:
        path.write_bytes(buf.getvalue())
    return n
