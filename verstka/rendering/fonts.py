"""Font metrics for text fitting (bundled Play, OFL) with width factors for other common families."""

from __future__ import annotations

import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import ImageFont

from verstka.rendering.cyrillic import measured_family  # noqa: E402  (no cycle: cyrillic imports fonts lazily)

FONT_DIR = Path(__file__).resolve().parents[1] / "fonts"

# relative average width vs Play for families we cannot bundle (empirical, conservative)
_WIDTH_FACTORS = {
    "play": 1.0,
    "arial": 1.0,
    "helvetica": 1.0,
    "calibri": 0.93,
    "segoe ui": 0.98,
    "roboto": 0.98,
    "inter": 1.03,
    "montserrat": 1.2,  # a wide geometric sans: 1.08 let LCT headings overflow their pills
    "vk sans display": 1.02,
    "vk sans": 1.0,
    "golos": 1.02,
    "pt sans": 0.98,
    "open sans": 1.08,
    "verdana": 1.25,
    "tahoma": 1.05,
    "georgia": 1.12,
    "consolas": 1.12,
    "courier new": 1.2,
    "times new roman": 0.92,
}
_UNKNOWN_FACTOR = 1.08  # a family we cannot measure is assumed a little wider than Play: overflow costs more than air
_MEASURE_PX = 64  # render size used for measuring; widths scale linearly


# the dataset templates' families keep the measured-as-Play × factor model they were tuned with (their decks must not
# move); every other family is measured with its real face when the machine has it (installed, or bundled with
# LibreOffice), else with the face that will stand in for it
_PINNED = ("play", "vk sans", "montserrat", "arial", "helvetica", "open sans", "inter", "golos", "pt sans", "roboto", "calibri", "consolas", "poppins")
_LO_FONT_DIRS = (Path("/Applications/LibreOffice.app/Contents/Resources/fonts/truetype"), Path("/usr/lib/libreoffice/share/fonts/truetype"), Path("/opt/libreoffice/share/fonts/truetype"))


def _norm(name: str) -> str:
    return re.sub(r"[\s_\-]+", "", (name or "").lower())


def _is_family_of(key: str, k: str) -> bool:
    """`key` names the family `k` or one of its faces («open sans light», «montserrat-regular»), not another family
    that merely starts with the same letters («playfair display» is not Play)."""
    return key.startswith(k) and (len(key) == len(k) or not key[len(k)].isalnum())


def is_pinned(family: Optional[str]) -> bool:
    key = (family or "").lower().strip()
    return not key or key.startswith("+") or any(_is_family_of(key, k) for k in _PINNED)


@lru_cache(maxsize=1)
def _bundled_index() -> dict[tuple[str, bool], str]:
    """(normalised family, bold) → file of the fonts LibreOffice ships (Noto Sans, Liberation, DejaVu, Carlito…)."""
    out: dict[tuple[str, bool], str] = {}
    for d in _LO_FONT_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix.lower() not in (".ttf", ".otf"):
                continue
            try:
                fam, style = ImageFont.truetype(str(f), 12).getname()
            except Exception:  # noqa: BLE001
                continue
            st = (style or "").lower()
            if "italic" in st or "oblique" in st:
                continue
            bold = "bold" in st
            if st in ("regular", "bold", "book", "roman", "normal") or not st:
                out.setdefault((_norm(fam), bold), str(f))
    return out


@lru_cache(maxsize=128)
def _face(family: str, bold: bool) -> Optional[tuple[str, int, bool, str]]:
    """(file, index, exact, face family) of the face that sets `family` on this machine: the family itself when
    installed or bundled with LibreOffice (exact), else fontconfig's substitute; None without fontconfig."""
    want = _norm(family)
    hit = _bundled_index().get((want, bold)) or (_bundled_index().get((want, False)) if bold else None)
    if hit:
        return hit, 0, True, family
    exe = shutil.which("fc-match")
    if not exe:
        return None
    try:
        res = subprocess.run([exe, "-f", "%{family}\t%{file}\t%{index}", f"{family}:{'bold' if bold else 'regular'}"], capture_output=True, text=True, timeout=5)
    except Exception:  # noqa: BLE001
        return None
    parts = (res.stdout or "").split("\t")
    if len(parts) < 2 or not parts[1] or not Path(parts[1]).exists():
        return None
    names = [n.strip() for n in parts[0].split(",") if n.strip()]
    exact = any(_norm(n) == want for n in names)
    try:
        index = int(parts[2]) if len(parts) > 2 and parts[2].strip() else 0
    except ValueError:
        index = 0
    return parts[1], index, exact, names[0] if names else family


@lru_cache(maxsize=128)
def _real_font(family: str, bold: bool) -> Optional[ImageFont.FreeTypeFont]:
    face = _face(family, bold)
    if face is None:
        return None
    try:
        return ImageFont.truetype(face[0], _MEASURE_PX, index=face[1])
    except Exception:  # noqa: BLE001
        return None


_NOTDEF_PROBE = "\U0010fffd"  # a private-use code point no text face maps: it draws the face's «.notdef» glyph
_COVER_CACHE: dict[tuple, dict[str, bool]] = {}


def _has_glyph(font: ImageFont.FreeTypeFont, ch: str) -> bool:
    """The face maps `ch` to a glyph of its own (not «.notdef»). Whitespace always counts as covered."""
    if ch.isspace():
        return True
    cache = _COVER_CACHE.setdefault((getattr(font, "path", None), getattr(font, "index", 0), id(font) if getattr(font, "path", None) is None else 0), {})
    got = cache.get(ch)
    if got is None:
        if "__notdef__" not in cache:
            m = font.getmask(_NOTDEF_PROBE)
            cache["__notdef__"] = (m.size, bytes(m), font.getlength(_NOTDEF_PROBE))  # type: ignore[assignment]
        nd = cache["__notdef__"]
        m = font.getmask(ch)
        got = not (m.size == nd[0] and font.getlength(ch) == nd[2] and bytes(m) == nd[1])  # type: ignore[index]
        cache[ch] = got
    return got


def _coverage_runs(font: ImageFont.FreeTypeFont, text: str) -> list[tuple[str, bool]]:
    """`text` cut into runs of characters the face has / lacks."""
    runs: list[tuple[str, bool]] = []
    for ch in text:
        c = _has_glyph(font, ch)
        if runs and runs[-1][1] == c:
            runs[-1] = (runs[-1][0] + ch, c)
        else:
            runs.append((ch, c))
    return runs


def substitute_of(family: Optional[str]) -> Optional[str]:
    """The face previews and PDFs set `family` in when it is not on this machine: its render stand-in (see
    `render_standin`, the table LibreOffice gets), else fontconfig's substitute for a family measured with it. None
    when the family is on this machine, or unknown."""
    sub = render_standin(family)
    if sub:
        return sub
    if is_pinned(family):
        return None
    face = _face(family.strip(), False)
    return None if face is None or face[2] else face[3]


# ---------------------------------------------------------------------------- stand-ins for the LibreOffice render
# LibreOffice resolves a family it does not have by name similarity and then glyph by glyph: «Open Sans» becomes
# OpenSymbol (serif digits, wide spaces) with Helvetica for the letters, «₽» comes from STIX Two Math. The render
# (verstka.ingest.render) hands it a replacement table instead: each missing family → one face of its class that this
# machine has, covers Cyrillic («₽» too, for the first choices) and is not wider than the layout measured the family
# (+5 %). The layout keeps measuring the family as before (the .pptx opens elsewhere, where the fallback is unknown).
_SYMBOL_RE = re.compile(r"symbol|wingding|webding|dingbat|marlett|mt extra|zapf|emoji|icons?\b|awesome|glyph", re.I)
_WEIGHT_WORDS = r"regular|book|roman|normal|thin|hairline|extra ?light|ultra ?light|light|medium|semi ?bold|demi ?bold|demi|extra ?bold|ultra ?bold|bold|heavy|black|italic|oblique"
_WEIGHT_TAIL_RE = re.compile(rf"[\s\-_]+(?:{_WEIGHT_WORDS})$", re.I)
# LibreOffice's own metric-compatible twins: left to it (Calibri → Carlito) when the twin covers Cyrillic
_LO_TWINS = {
    "calibri": "Carlito",
    "cambria": "Caladea",
    "arial": "Liberation Sans",
    "helvetica": "Liberation Sans",
    "arial narrow": "Liberation Sans Narrow",
    "times new roman": "Liberation Serif",
    "times": "Liberation Serif",
    "courier new": "Liberation Mono",
    "courier": "Liberation Mono",
}
_CLASS_RULES = (
    ("mono", re.compile(r"mono|consol|courier|menlo|monaco|\bcode\b|typewriter|fixed", re.I)),
    ("display_condensed", re.compile(r"bebas|anton|league gothic|oswald|fjalla|teko|big shoulders|six caps|antonio|impact|haettenschweiler", re.I)),
    ("condensed", re.compile(r"condensed|narrow|compressed|\bcond\b", re.I)),
    (
        "serif",
        re.compile(
            r"(?<!sans )serif|times|georgia|garamond|baskerville|playfair|merriweather(?! sans)|\blora\b|bodoni|didot|caslon|cambria|"
            r"palatino|antiqua|minion|charter|crimson|cormorant|spectral|literata|tinos|gelasio|caladea|rockwell|slab|"
            r"constantia|sitka|\bcardo\b|\bforum\b|\bprata\b|gilda|yeseva|abril|cinzel|marcellus|vollkorn|domine|"
            r"frank ruhl|old standard|lustria|alice\b|trirong|myeongjo|\bultra\b|\barvo\b|rokkitt|bitter|noticia",
            re.I,
        ),
    ),
)
_STANDINS = {
    "mono": ("DejaVu Sans Mono", "Menlo", "Liberation Mono", "Courier New"),
    "display_condensed": ("DIN Condensed", "PT Sans Narrow", "Liberation Sans Narrow", "Arial Narrow"),
    "condensed": ("PT Sans Narrow", "Liberation Sans Narrow", "Arial Narrow", "DejaVu Sans Condensed"),
    "serif": ("Noto Serif", "PT Serif", "Liberation Serif", "Times New Roman", "Georgia"),
    "sans": ("Noto Sans", "Helvetica Neue", "PT Sans", "Liberation Sans", "Arial", "DejaVu Sans"),
}
_STANDIN_SLACK = 1.05
_WIDTH_SAMPLE = "Выручка кофейни за 30 дней составила 900 000 рублей, рост 26,5 % — Revenue"


def _base_name(family: str) -> str:
    """`family` without trailing weight/style words: «Calibri Light» → «calibri», «Open Sans SemiBold» → «open sans»."""
    name = family.strip().lower()
    while True:
        cut = _WEIGHT_TAIL_RE.sub("", name)
        if cut == name or not cut:
            return name
        name = cut


def font_class(family: str) -> str:
    """mono / display_condensed / condensed / serif / sans, from the family name."""
    for cls, rx in _CLASS_RULES:
        if rx.search(family):
            return cls
    return "sans"


@lru_cache(maxsize=64)
def _installed_face(family: str) -> Optional[ImageFont.FreeTypeFont]:
    """The regular face of `family` when this machine has the family itself (installed or bundled with LibreOffice)."""
    face = _face(family, False)
    if face is None or not face[2]:
        return None
    return _real_font(family, False)


@lru_cache(maxsize=256)
def render_standin(family: Optional[str]) -> Optional[str]:
    """The installed family LibreOffice should set `family` in, or None: the family is on this machine (or there is no
    fontconfig to tell), it is a theme reference, a symbol font or a face name with a weight, LibreOffice's own metric
    twin covers it, or no face of its class fits."""
    name = (family or "").strip()
    if not name or name.startswith("+") or _SYMBOL_RE.search(name):
        return None
    face = _face(name, False)
    if face is None or face[2]:
        return None
    base = _base_name(name)
    if base != name.lower():
        # a face name with a weight («Lato Light», «Open Sans SemiBold», «Montserrat-Regular»): LibreOffice matches
        # it by weight and sets it in one face of that weight (Helvetica Light); a stand-in family would lose the weight
        return None
    twin = _LO_TWINS.get(base)
    if twin:
        tf = _installed_face(twin)
        if tf is not None and _has_glyph(tf, "ж"):
            return None
    play = _font(False).getlength(_WIDTH_SAMPLE) / _MEASURE_PX
    limit = text_width_pt(_WIDTH_SAMPLE, name, 1.0) / play * _STANDIN_SLACK
    for cand in _STANDINS[font_class(name)]:
        cf = _installed_face(cand)
        if cf is None or not _has_glyph(cf, "ж"):
            continue
        if cf.getlength(_WIDTH_SAMPLE) / _MEASURE_PX / play <= limit:
            return cand
    return None


# ---------------------------------------------------------------------------- installed faces without Cyrillic
# A family this machine HAS can still lack Cyrillic in the face LibreOffice picks (macOS: Avenir, Optima, Didot,
# Bodoni 72, Futura Medium…): LibreOffice then sets the Latin letters, digits and punctuation of a run in the family
# and every Cyrillic letter in a fallback (Helvetica, Times, even Snell Roundhand for Chalkboard) — two faces inside
# one word. A replacement table would restyle the template's Latin chrome too, so the render copy
# (verstka.ingest.render) sets only the runs that hold Cyrillic in a stand-in: the family's own Cyrillic sibling
# (Avenir → Avenir Next, Chalkboard → Chalkboard SE), else a face of its class, within the width the layout measured.
_HEAVY_WORDS_RE = re.compile(r"semi ?bold|demi ?bold|\bdemi\b|extra ?bold|ultra ?bold|\bbold\b|heavy|black", re.I)
_NARROW_RE = re.compile(r"condensed|narrow|compressed|\bcond\b", re.I)
# geometric sans without Cyrillic: a geometric stand-in reads closer than a humanist one (Futura → Avenir Next)
_GEOMETRIC_RE = re.compile(r"futura|avenir|century gothic|tw cen|gotham|spartan|\bjost\b|brandon|kabel|eurostile", re.I)
_GEOMETRIC_STANDINS = ("Avenir Next", "Century Gothic", "URW Gothic", "TeX Gyre Adventor")


@lru_cache(maxsize=1)
def _installed_families() -> tuple[str, ...]:
    """The families fontconfig lists on this machine (first name of each face); () without fontconfig."""
    exe = shutil.which("fc-list")
    if not exe:
        return ()
    try:
        res = subprocess.run([exe, ":", "family"], capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return ()
    return tuple(sorted({line.split(",")[0].strip() for line in (res.stdout or "").splitlines() if line.split(",")[0].strip()}))


def _cyrillic_siblings(base: str) -> list[str]:
    """Installed families of the same design line as `base` («avenir» → Avenir Next, Avenir Next Condensed), plain
    widths first; the caller checks their Cyrillic."""
    names = [n for n in _installed_families() if n.lower().startswith(base + " ") and not _WEIGHT_TAIL_RE.search(n)]
    if not _NARROW_RE.search(base):
        names = [n for n in names if not _NARROW_RE.search(n)] + [n for n in names if _NARROW_RE.search(n)]
    return sorted(names, key=lambda n: (bool(_NARROW_RE.search(n)) and not _NARROW_RE.search(base), len(n)))


def is_installed(family: Optional[str]) -> bool:
    """This machine has `family` itself (installed or bundled with LibreOffice), not a fontconfig substitute."""
    name = (family or "").strip()
    return bool(name) and not name.startswith("+") and _installed_face(name) is not None


def is_heavy_face_name(family: Optional[str]) -> bool:
    """`family` names a heavy face of its family («Avenir Heavy», «Lato Black», «Open Sans SemiBold»)."""
    name = (family or "").strip().lower()
    base = _base_name(name)
    return base != name and bool(_HEAVY_WORDS_RE.search(name[len(base):]))


@lru_cache(maxsize=256)
def cyrillic_standin(family: Optional[str], bold: bool = False) -> Optional[str]:
    """The installed family a run of Cyrillic text set in `family` (at this weight) is rendered in, or None.

    Only for a family this machine has whose face LibreOffice picks lacks Cyrillic. A face name with a weight is
    checked both as named and through its family (bold for a heavy name), since LibreOffice uses either: «Avenir
    Heavy» → Avenir Black + Helvetica, «Avenir Next Heavy» → its Heavy face + Helvetica, «Futura Medium» → Futura
    (Medium, no Cyrillic), «Futura Bold» → Futura Bold (has Cyrillic, no stand-in). When only the named face lacks
    Cyrillic the stand-in is its own family («Avenir Next Heavy» → Avenir Next, set bold). None when those
    faces have Cyrillic, the family is missing (`render_standin` replaces it everywhere), it is a theme reference or a
    symbol font, LibreOffice's metric twin sets it (Courier → Liberation Mono), or no stand-in fits the width."""
    name = (family or "").strip()
    if not name or name.startswith("+") or _SYMBOL_RE.search(name):
        return None
    base = _base_name(name)
    heavy = bold or is_heavy_face_name(name)  # LibreOffice sets a heavy face name as its family, bold
    face = _face(name, bold)
    bface = _face(base, heavy) if base != name.lower() else None
    named_ok = face is not None and face[2]
    base_ok = bface is not None and bface[2]
    if not named_ok and not base_ok:  # a face name fontconfig does not list («Futura Medium») is set in its family
        return None
    twin = _LO_TWINS.get(base)
    if twin:
        tf = _installed_face(twin)
        if tf is not None and _has_glyph(tf, "ж"):
            return None
    # the faces LibreOffice may set the run in: the named face («Avenir Next Heavy» → its Heavy face) and the family's
    # («Avenir Heavy» → Avenir Black, «Futura Medium» → Futura); a stand-in when either lacks Cyrillic
    lacking = []
    for probe, ok, weight in ((name, named_ok, bold), (base, base_ok, heavy)):
        pf = _real_font(probe, weight) if ok else None
        if pf is not None and not _has_glyph(pf, "ж"):
            lacking.append(probe)
    if not lacking:
        return None
    if base_ok and base not in lacking:
        # only the named face lacks Cyrillic: its own family at the run's weight (a heavy name is set bold by the caller)
        return bface[3]  # type: ignore[index]
    play = _font(False).getlength(_WIDTH_SAMPLE) / _MEASURE_PX
    limit = text_width_pt(_WIDTH_SAMPLE, name, 1.0) / play * _STANDIN_SLACK
    geometric = _GEOMETRIC_STANDINS if _GEOMETRIC_RE.search(name) and font_class(name) == "sans" else ()
    for cand in (*_cyrillic_siblings(base), *geometric, *_STANDINS[font_class(name)]):
        if _norm(cand) in (_norm(name), _norm(base)):
            continue
        cf = _installed_face(cand)
        if cf is None or not _has_glyph(cf, "ж"):
            continue
        if cf.getlength(_WIDTH_SAMPLE) / _MEASURE_PX / play <= limit:
            return cand
    return None


@lru_cache(maxsize=256)
def glyph_standin(family: Optional[str], ch: str = "₽", bold: bool = False) -> Optional[str]:
    """The installed family a lone `ch` of a run LibreOffice sets in `family` is drawn in, or None when that face has
    it (or `family` is a theme reference or a symbol font, or no face of its class has it).

    LibreOffice takes a glyph the face lacks from whichever face has it: «₽» comes from STIX Two Math, a thin serif
    sign beside sans digits (Arial, Trebuchet MS, Verdana, Gill Sans, Georgia, Avenir Next have no «₽» on macOS). The
    stand-in is the first installed face of the family's class (then a sans) with `ch` at this weight. `family` is
    the family LibreOffice sets the run in (after `render_standin` / `cyrillic_standin`); a family missing here is
    treated as lacking `ch` (LibreOffice's own fallback face)."""
    name = (family or "").strip()
    if not name or name.startswith("+") or _SYMBOL_RE.search(name):
        return None
    face = _face(name, bold)
    if face is not None and face[2]:
        pf = _real_font(name, bold)
        if pf is None or _has_glyph(pf, ch):
            return None
    cls = font_class(name)
    for cand in dict.fromkeys((*_STANDINS[cls], *_STANDINS["sans"])):
        if _norm(cand) == _norm(name):
            continue
        cf = _installed_face(cand)
        if cf is None or not _has_glyph(cf, ch):
            continue
        if bold:
            bf = _real_font(cand, True)
            if bf is None or not _has_glyph(bf, ch):
                continue
        return cand
    return None


def font_path(family: Optional[str] = None, bold: bool = False) -> Path:
    name = "Play-Bold.ttf" if bold else "Play-Regular.ttf"
    return FONT_DIR / name


def width_factor(family: Optional[str]) -> float:
    if not family:
        return 1.0
    key = family.lower().strip()
    if key.startswith("+"):
        return 1.0  # a theme font reference: resolved elsewhere, measured as Play
    for k, v in _WIDTH_FACTORS.items():
        if _is_family_of(key, k):
            return v
    return _UNKNOWN_FACTOR


@lru_cache(maxsize=8)
def _font(bold: bool) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_path(None, bold)), _MEASURE_PX)


def is_measured(family: Optional[str]) -> bool:
    """True when the family's widths are known: Play itself, a theme reference measured as Play, a pinned family with
    a calibrated factor, or a face measured with its own font file. False for a face estimated with a stand-in (a
    substitute or the unknown-family factor) — callers keep ≥ 8 % slack for it."""
    if not family:
        return True
    key = family.lower().strip()
    if key.startswith("+"):
        return True
    if is_pinned(family):
        return True  # the dataset families keep the model their decks were tuned with (no extra slack)
    face = _face(family.strip(), False)
    return bool(face and face[2])


def text_width_pt(text: str, family: Optional[str], size_pt: float, bold: bool = False, *, caps: bool = False, spc_pt: float = 0.0) -> float:
    """Width of `text` set in `family` at `size_pt`. `caps`: the run is set in capitals (cap="all" inherited from the
    master), measured upper-cased; `spc_pt`: letter-spacing (spc/100) added after every character."""
    if not text:
        return 0.0
    family = measured_family(family)  # a family without Cyrillic is measured in the stand-in the deck will set (cyrillic.py)
    t = text.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2060", "")
    if caps:
        t = t.upper()
    real = None if is_pinned(family) else _real_font(family.strip(), bold)
    if real is not None:
        w = 0.0
        for seg, covered in _coverage_runs(real, t):
            if covered:
                w += real.getlength(seg) / _MEASURE_PX * size_pt
            else:
                # glyphs the face lacks (Cyrillic in Futura Medium, «₽» in most Latin faces) are set by the renderer
                # in a fallback face we cannot name: measured as an unknown family (Play × 1.08, a little wide), not
                # with the face's «.notdef» box
                w += _font(bold).getlength(seg) / _MEASURE_PX * size_pt * _UNKNOWN_FACTOR
    else:
        w = _font(bold).getlength(t) / _MEASURE_PX * size_pt * width_factor(family)
    if spc_pt:
        w += spc_pt * len(t)
    return w


def wrap_lines(text: str, family: Optional[str], size_pt: float, bold: bool, width_pt: float, *, caps: bool = False, spc_pt: float = 0.0) -> list[str]:
    """Greedy word wrap; over-long words are split by characters. `caps`/`spc_pt` as in `text_width_pt`."""
    if width_pt <= 0:
        return [text]

    def width(t: str) -> float:
        return text_width_pt(t, family, size_pt, bold, caps=caps, spc_pt=spc_pt)

    lines: list[str] = []
    for raw in text.split("\n"):
        # break at ordinary spaces only: a no-break space keeps «27 млн» and «в VK» together, as PowerPoint does
        words = [w for w in re.split(r"[ \t\r]+", raw) if w]
        if not words:
            lines.append("")
            continue
        cur = ""
        for w in words:
            cand = (cur + " " + w).strip()
            if width(cand) <= width_pt:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            if width(w) <= width_pt:
                cur = w
            else:
                piece = ""
                for ch in w:
                    if width(piece + ch) <= width_pt:
                        piece += ch
                    else:
                        lines.append(piece)
                        piece = ch
                cur = piece
        lines.append(cur)
    return lines


def measure_text_lines(text: str, family: Optional[str], size_pt: float, bold: bool, width_pt: float, *, caps: bool = False, spc_pt: float = 0.0) -> int:
    return len(wrap_lines(text, family, size_pt, bold, width_pt, caps=caps, spc_pt=spc_pt))


@lru_cache(maxsize=256)
def left_bearing_em(ch: str, bold: bool = False) -> float:
    """How far the ink of a glyph starts right of its origin, in em (Play): the «1» of a 120 pt figure stands 14 pt
    right of the edge its heading starts at — a large figure is set that much to the left to look aligned."""
    from PIL import Image, ImageDraw

    if not ch or ch.isspace():
        return 0.0
    f = ImageFont.truetype(str(font_path(None, bold)), 200)
    im = Image.new("L", (480, 360), 0)
    ImageDraw.Draw(im).text((120, 40), ch, font=f, fill=255)
    bb = im.getbbox()
    return max(0.0, (bb[0] - 120) / 200) if bb else 0.0


@lru_cache(maxsize=4)
def figure_metrics_em(bold: bool = False) -> tuple[float, float]:
    """(descent, digit height) of the measuring font, in em: where the top of a figure's digits sits in its line."""
    f = ImageFont.truetype(str(font_path(None, bold)), 200)
    _, descent = f.getmetrics()
    top = f.getbbox("0", anchor="ls")[1]
    return descent / 200, -top / 200
