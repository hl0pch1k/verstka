"""Text → SVG paths (needs fontTools: pip install fonttools) with the real fonts of «Слои» (Unbounded, Manrope) so GitHub shows the brand type without web fonts."""
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
import re

import os
FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "verstka", "fonts")
FONTS = {
    "U": f"{FD}/Unbounded/Unbounded-Bold.ttf",
    "UR": f"{FD}/Unbounded/Unbounded-Regular.ttf",
    "M": f"{FD}/Manrope/Manrope-Bold.ttf",
    "MR": f"{FD}/Manrope/Manrope-Regular.ttf",
}
_cache = {}


def _font(key):
    if key not in _cache:
        f = TTFont(FONTS[key])
        _cache[key] = (f, f.getGlyphSet(), f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm, _kern(f))
    return _cache[key]


def _kern(f):
    """Pair kerning from GPOS PairPos format 1 (enough for display words)."""
    out = {}
    if "GPOS" not in f:
        return out
    for lk in f["GPOS"].table.LookupList.Lookup:
        if lk.LookupType != 2:
            continue
        for st in lk.SubTable:
            if getattr(st, "Format", None) == 1:
                cov = st.Coverage.glyphs
                for i, ps in enumerate(st.PairSet):
                    for pv in ps.PairValueRecord:
                        v = getattr(pv.Value1, "XAdvance", 0) if pv.Value1 else 0
                        if v:
                            out[(cov[i], pv.SecondGlyph)] = v
            elif getattr(st, "Format", None) == 2:
                cov = set(st.Coverage.glyphs)
                c1 = st.ClassDef1.classDefs
                c2 = st.ClassDef2.classDefs
                out.setdefault("_cls", []).append((cov, c1, c2, st.Class1Record))
    return out


def _pair(kern, a, b):
    v = kern.get((a, b))
    if v is not None:
        return v
    for cov, c1, c2, recs in kern.get("_cls", []):
        if a in cov:
            r = recs[c1.get(a, 0)].Class2Record[c2.get(b, 0)]
            x = getattr(r.Value1, "XAdvance", 0) if r.Value1 else 0
            if x:
                return x
    return 0


def width(s, key, size, track=0.0):
    f, gs, cmap, hmtx, upm, kern = _font(key)
    sc = size / upm
    w, prev = 0.0, None
    for ch in s:
        g = cmap.get(ord(ch)) or cmap.get(ord("?"))
        if prev:
            w += _pair(kern, prev, g) * sc
        w += hmtx[g][0] * sc + track * size
        prev = g
    return w - (track * size if s else 0)


DEFS = {}


def flush():
    """<path id> glyph definitions used since the last flush (in font units, y up)."""
    out = "".join(DEFS.values())
    DEFS.clear()
    return out


def _gid(key, g):
    return f"{key}-" + re.sub(r"[^A-Za-z0-9_.-]", "_", g)


def path(s, key, size, x, y, fill, track=0.0, anchor="start", opacity=None, extra=""):
    """Text as reused glyph outlines: each glyph is defined once per file and placed with <use>. Baseline at y."""
    f, gs, cmap, hmtx, upm, kern = _font(key)
    sc = size / upm
    if anchor != "start":
        w = width(s, key, size, track)
        x = x - (w if anchor == "end" else w / 2)
    uses = []
    cx, prev = x, None
    for ch in s:
        g = cmap.get(ord(ch)) or cmap.get(ord("?"))
        if prev:
            cx += _pair(kern, prev, g) * sc
        if ch != " ":
            gid = _gid(key, g)
            if gid not in DEFS:
                pen = SVGPathPen(gs)
                gs[g].draw(pen)
                d = pen.getCommands()
                d = re.sub(r"-?\d+\.\d+", lambda m: str(round(float(m.group()))), d)
                DEFS[gid] = f'<path id="{gid}" d="{d}"/>'
            uses.append(f'<use href="#{gid}" transform="matrix({sc:.5g} 0 0 {-sc:.5g} {cx:.1f} {y:.1f})"/>')
        cx += hmtx[g][0] * sc + track * size
        prev = g
    op = f' fill-opacity="{opacity}"' if opacity is not None else ""
    return f'<g fill="{fill}"{op}{extra}>' + "".join(uses) + "</g>"
