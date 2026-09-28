"""Native PowerPoint charts styled from template tokens.

A chart is drawn the way a designer would finish it, whatever the template:

* colours come from the template: accent.1 first, then the series colours of the template's own chart parts
  (schemeClr resolved through the theme), the manifest series colours and the theme accents — every colour visible
  on the ground, never a text or background colour, and ≥ ΔE 20 from every other, so no two series look alike;
* one series with a highlight: the highlight in accent.1, the other bars accent.1 mixed toward the ground (a tint of
  the brand colour, never a neutral grey); several series that tell a story (Было/Стало, 2024/2025, Факт/План): the
  latest in the accent, earlier ones in its tint, a plan as an outline or a dashed line;
* a word unit is written once, in a muted caption at the top left (or not at all when the caller already put it
  above the chart), and every label is a plain number of that one scale; a one-glyph unit (%, ₽) rides on every
  label; zero labels are hidden; the value axis and gridlines go while labels carry the values;
* type from the template: sizes snapped to its type scale, bold only where the template speaks in bold (elsewhere
  the highlight steps up a size in the accent);
* long category labels (> 12 characters) or many categories turn a column chart into horizontal bars read top-down;
* the plot area has a manual layout that reserves room for every label, so nothing is cut and the bars fill the
  frame exactly; chart and plot area are transparent, so the chart sits on the slide's own ground;
* lines are 2.25 pt with ringed markers and labels placed off the line; an area is a soft fill under a 2.25 pt edge;
  pies and doughnuts show percentages inside the slices that fit them, no leader lines.
"""

from __future__ import annotations

import copy
import io
import math
import re
import weakref
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from lxml import etree
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_MARKER_STYLE, XL_TICK_LABEL_POSITION, XL_TICK_MARK
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.opc.constants import CONTENT_TYPE as CT
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.slide import Slide
from pptx.util import Emu, Pt

from verstka.rendering.fonts import text_width_pt, wrap_lines
from verstka.schemas.common import Bbox, contrast_ratio, relative_luminance, rgb_to_lab
from verstka.schemas.outline import ChartSpec, DeckOutline, Series
from verstka.schemas.template import ChartStyleSpec, Typography

_TYPE_MAP = {
    "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "bar": XL_CHART_TYPE.BAR_CLUSTERED,
    "line": XL_CHART_TYPE.LINE_MARKERS,
    "area": XL_CHART_TYPE.AREA,
    "pie": XL_CHART_TYPE.PIE,
    "doughnut": XL_CHART_TYPE.DOUGHNUT,
}

_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EMU_PER_PT = 12700

MIN_FILL_CONTRAST = 1.4  # a bar, slice or line must stand off its ground at least this much
DARK_MUTED_DE = 34.0  # on a dark ground the stepped-back bars are as bright as this distance from the accent allows
MIN_SERIES_DE = 20.0  # CIE76 distance between two series colours that a reader can tell apart
SAME_HUE_DE = 32.0  # … and between two shades of the same hue
MUTED_TOWARD_GROUND = 0.58  # the bars that step back: accent.1 moved this share of the way to the ground
LONG_LABEL_CHARS = 12  # a category label longer than this reads better as a horizontal bar
PAIR_LABEL_CHARS = 20  # … unless the chart has only two categories: two wide columns take labels this long
MAX_COLUMNS = 7  # more categories than this: horizontal bars
HOLE_SIZE = 56  # doughnut hole, % of the diameter
BOLD_VOICE_SHARE = 0.3  # the template sets its display / h1 in bold at least this often: emphasis may be bold
LABEL_SEP = ": "  # «Было: 48» — a series named on its label


def _c(tag: str) -> str:
    return f"{{{_C}}}{tag}"


def _a(tag: str) -> str:
    return f"{{{_A}}}{tag}"


def _local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


# ---------------------------------------------------------------------------------------------- colour helpers


def _norm(hex_: Optional[str]) -> Optional[str]:
    h = (hex_ or "").strip().lstrip("#").upper()
    return h if len(h) == 6 and all(ch in "0123456789ABCDEF" for ch in h) else None


def _rgb(hex_: str) -> RGBColor:
    return RGBColor.from_string(hex_.upper())


def _rgb_t(hex_: str) -> tuple[int, int, int]:
    return int(hex_[0:2], 16), int(hex_[2:4], 16), int(hex_[4:6], 16)


def _mix(fg: str, bg: str, share: float) -> str:
    """`share` of fg over bg."""
    a = [int(fg[i : i + 2], 16) for i in (0, 2, 4)]
    b = [int(bg[i : i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{max(0, min(255, int(round(x * share + y * (1 - share))))):02X}" for x, y in zip(a, b))


def delta_e(a: str, b: str) -> float:
    """CIE76 distance between two hex colours."""
    la, lb = rgb_to_lab(*_rgb_t(a)), rgb_to_lab(*_rgb_t(b))
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(la, lb)))


def _chroma(hex_: str) -> float:
    _, a, b = rgb_to_lab(*_rgb_t(hex_))
    return math.hypot(a, b)


def _lightness(hex_: str) -> float:
    return rgb_to_lab(*_rgb_t(hex_))[0]


def _hue_gap(a: str, b: str) -> float:
    """Angle between two colours' Lab hues (degrees); a near-grey counts as a different hue from anything."""
    _, a1, b1 = rgb_to_lab(*_rgb_t(a))
    _, a2, b2 = rgb_to_lab(*_rgb_t(b))
    if math.hypot(a1, b1) < 12 or math.hypot(a2, b2) < 12:
        return 180.0
    d = abs(math.degrees(math.atan2(b1, a1)) - math.degrees(math.atan2(b2, a2))) % 360
    return min(d, 360 - d)


def _is_dark(hex_: str) -> bool:
    return relative_luminance(hex_) < 0.18


def _is_data_color(hex_: str) -> bool:
    """False for a text or background colour (a near-black or near-white grey): a slice or a series never takes one."""
    return not (_chroma(hex_) < 12 and not (22 <= _lightness(hex_) <= 92))


def muted_tint(accent: str, ground: str, toward: float = MUTED_TOWARD_GROUND) -> str:
    """accent.1 moved `toward` of the way to the ground: the colour of the bars that step back behind the highlight.
    It is a tint (or shade) of the brand colour, never a grey, it stands off the ground (≥ 1.4:1; on a dark ground as
    bright as a clear step from the accent allows, since a faint shade sinks into it) and it stays ≥ ΔE 20 away from
    the accent itself."""
    accent, ground = _norm(accent) or "0077FF", _norm(ground) or "FFFFFF"
    share = 1.0 - toward
    if _is_dark(ground) and toward == MUTED_TOWARD_GROUND:
        # on a dark ground a faint shade sinks into it: the brightest shade that is still a clear step from the accent
        for i in range(20):
            s = 0.8 - 0.02 * i
            if s <= share or delta_e(_mix(accent, ground, s), accent) >= DARK_MUTED_DE:
                share = max(share, s)
                break
    out = _mix(accent, ground, share)
    while contrast_ratio(out, ground) < MIN_FILL_CONTRAST and share < 0.86:
        share += 0.02
        out = _mix(accent, ground, share)
    # too close to the accent now: step back toward the ground as long as it stays visible
    while delta_e(out, accent) < MIN_SERIES_DE and share > 0.2 and contrast_ratio(_mix(accent, ground, share - 0.04), ground) >= MIN_FILL_CONTRAST:
        share -= 0.04
        out = _mix(accent, ground, share)
    if delta_e(out, accent) < MIN_SERIES_DE:
        # an accent that barely differs from its ground (pale accent on white): step toward the text side instead
        out = _mix(accent, "000000" if not _is_dark(ground) else "FFFFFF", 0.6)
    return out


def _readable_text(text_hex: Optional[str], ground: str) -> str:
    t = _norm(text_hex)
    if t and contrast_ratio(t, ground) >= 3.0:
        return t
    return "FFFFFF" if contrast_ratio("FFFFFF", ground) >= contrast_ratio("000000", ground) else "1A1A1A"


def _muted_text(text: str, ground: str) -> str:
    """The secondary text colour for category labels and legends: text eased toward the ground, still ≥ 4.5:1."""
    for share in (0.66, 0.72, 0.78, 0.85, 0.92):
        c = _mix(text, ground, share)
        if contrast_ratio(c, ground) >= 4.5:
            return c
    return text


def _rule_color(neutral_hex: Optional[str], text: str, ground: str) -> str:
    """The baseline hairline: the template's divider when it reads as a quiet line on this ground (visible, not loud,
    and on the text's side of the ground — lighter than a dark ground), else text eased far toward the ground."""
    n = _norm(neutral_hex)
    floor = 1.45 if _is_dark(ground) else 1.2  # the same ratio reads fainter near black
    if n and floor <= contrast_ratio(n, ground) <= 4.0:
        lg = relative_luminance(ground)
        if (relative_luminance(n) > lg) == (relative_luminance(text) > lg):
            return n
    for share in (0.25, 0.3, 0.4):
        c = _mix(text, ground, share)
        if contrast_ratio(c, ground) >= floor:
            return c
    return _mix(text, ground, 0.5)


def _label_on(fill: str, text: str, ground: str) -> str:
    """Text colour for a label printed on a filled slice."""
    for c in ("FFFFFF", text, ground, "1A1A1A"):
        if contrast_ratio(c, fill) >= 3.0:
            return c
    return "FFFFFF" if contrast_ratio("FFFFFF", fill) >= contrast_ratio("1A1A1A", fill) else "1A1A1A"


def _quiet_fill(text: str, ground: str) -> str:
    """The colour of an «Прочее» slice: text eased toward the ground — present, deliberately without a hue."""
    for share in (0.22, 0.28, 0.36, 0.46):
        c = _mix(text, ground, share)
        if contrast_ratio(c, ground) >= MIN_FILL_CONTRAST:
            return c
    return _mix(text, ground, 0.55)


def chart_palette(base: Sequence[str], ground: Optional[str], n: int, extra: Iterable[str] = ()) -> list[str]:
    """`n` series colours: `base[0]` (accent.1) first, then candidates from `base` and `extra` in order that are data
    colours (not a near-black or near-white grey), visible on the ground (≥ 1.4:1) and ≥ ΔE 20 from every colour
    already taken. When the template runs out of such colours, tints and shades of the taken ones fill in — still
    ΔE ≥ 20 from all — and only then a nearer colour is accepted."""
    n = max(1, n)
    cands: list[str] = []
    for h in [*base, *extra]:
        h = _norm(h)
        if h and h not in cands:
            cands.append(h)
    if not cands:
        cands = ["0077FF"]
    g = _norm(ground)
    ground_ = g or "FFFFFF"
    first = cands[0]
    visible = [h for h in cands[1:] if _is_data_color(h) and contrast_ratio(h, ground_) >= MIN_FILL_CONTRAST]
    rest = sorted(visible, key=lambda h: (_chroma(h) < 12, visible.index(h)))
    out = [first]

    def far_from_all(h: str, de: float, strict: bool = True) -> bool:
        # two shades of one hue need a bigger step than two hues to read as different series
        return all(delta_e(h, o) >= de and (not strict or _hue_gap(h, o) >= 30 or delta_e(h, o) >= max(de, SAME_HUE_DE)) for o in out)

    # strong, clearly different hues first (another hue family, well visible), then merely distinct colours
    passes = (
        lambda h: _chroma(h) >= 12 and contrast_ratio(h, ground_) >= 2.0 and far_from_all(h, MIN_SERIES_DE * 1.5) and all(_hue_gap(h, o) >= 40 for o in out),
        lambda h: far_from_all(h, MIN_SERIES_DE * 1.5),
        lambda h: far_from_all(h, MIN_SERIES_DE),
    )
    for ok in passes:
        for h in rest:
            if len(out) >= n:
                return out
            if h not in out and ok(h):
                out.append(h)
    far = "FFFFFF" if _is_dark(ground_) else "000000"

    def synth() -> list[str]:
        s = [muted_tint(first, ground_), _mix(first, far, 0.55), _mix(first, ground_, 0.72), _mix(first, far, 0.3)]
        for c in out[1:]:
            s += [muted_tint(c, ground_), _mix(c, far, 0.55)]
        return [h for h in s if contrast_ratio(h, ground_) >= MIN_FILL_CONTRAST]

    for de, strict in ((MIN_SERIES_DE, True), (MIN_SERIES_DE, False), (MIN_SERIES_DE * 0.6, False)):
        for h in synth() + rest:
            if len(out) >= n:
                return out
            if h not in out and far_from_all(h, de, strict):
                out.append(h)
    i = 0
    while len(out) < n:  # a very long series list: repeat, never fail
        out.append(out[i % len(out)])
        i += 1
    return out


def pie_shades(values: Sequence[Optional[float]], accent: str, ground: Optional[str], quiet_idx: Iterable[int] = (), text: Optional[str] = None) -> list[tuple[str, float]]:
    """Slice colours of a pie or a doughnut as (base colour, share over the ground): the largest slice in the accent
    (share 1), the others in tints of it that step toward the ground with the slice's rank (the bigger the part, the
    stronger the colour), every tint still visible on the ground; a remainder («Прочее») the text colour eased
    toward the ground. One hue reads as one whole; the eye goes to the largest part first. A tint is the accent laid
    over the ground at that share — the solid colour of a slice, or the accent at that opacity on a legend swatch."""
    accent = _norm(accent) or "0077FF"
    ground_ = _norm(ground) or "FFFFFF"
    text_ = _readable_text(text, ground_)
    n = len(values)
    quiet_set = set(quiet_idx)
    quiet_share = next((sh for sh in (0.22, 0.28, 0.36, 0.46) if contrast_ratio(_mix(text_, ground_, sh), ground_) >= MIN_FILL_CONTRAST), 0.55)
    out: list[tuple[str, float]] = [(text_, quiet_share)] * n
    order = sorted((j for j in range(n) if j not in quiet_set), key=lambda j: (-(values[j] or 0.0), j))
    if not order:
        return out
    out[order[0]] = (accent, 1.0)
    m = len(order) - 1
    if m:
        # tints evenly spaced by how different they look (CIE ΔE along the way from the accent to the ground): two
        # neighbours up to ΔE 32 apart, closer only when many slices share the room; the palest still clearly off the
        # ground (a shade on a dark ground keeps 1.6:1)
        floor = 1.6 if _is_dark(ground_) else MIN_FILL_CONTRAST
        path: list[tuple[float, float]] = [(1.0, 0.0)]
        share = 1.0
        while share > 0.1:
            share = round(share - 0.02, 3)
            c = _mix(accent, ground_, share)
            if contrast_ratio(c, ground_) < floor:
                break
            path.append((share, path[-1][1] + delta_e(c, _mix(accent, ground_, share + 0.02))))
        total = path[-1][1]
        step = min(32.0, total / m) if total > 0 else 0.0
        for r, j in enumerate(order[1:]):
            target = step * (r + 1)
            sh = next((a for a, d in path if d >= target - 1e-6), path[-1][0])
            out[j] = (accent, sh)
    return out


def pie_palette(values: Sequence[Optional[float]], accent: str, ground: Optional[str], quiet_idx: Iterable[int] = (), text: Optional[str] = None) -> list[str]:
    """The solid colours of `pie_shades`: each base colour laid over the ground at its share."""
    ground_ = _norm(ground) or "FFFFFF"
    return [base if share >= 1.0 else _mix(base, ground_, share) for base, share in pie_shades(values, accent, ground_, quiet_idx, text)]


# ---------------------------------------------------------------------------------------------- theme & ground


def _theme_scheme(slide: Slide) -> dict[str, str]:
    """clrScheme of the slide's master theme, keyed dk1/lt1/…/accent6, plus the master's colour map (bg1→lt1 …)."""
    out: dict[str, str] = {}
    try:
        master = slide.slide_layout.slide_master
        theme = etree.fromstring(master.part.part_related_by(RT.THEME).blob)
    except Exception:  # noqa: BLE001
        return out
    scheme = theme.find(f".//{_a('clrScheme')}")
    if scheme is not None:
        for child in scheme:
            if not isinstance(child.tag, str) or not len(child):
                continue
            clr = child[0]
            val = clr.get("val") if _local(clr) == "srgbClr" else clr.get("lastClr")
            if _norm(val):
                out[_local(child)] = _norm(val)
    cmap = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2"}
    try:
        cm = master._element.find(f"{{{_P}}}clrMap")
        if cm is not None:
            cmap.update({k: v for k, v in cm.attrib.items()})
    except Exception:  # noqa: BLE001
        pass
    for k, v in cmap.items():
        if v in out and k not in out:
            out[k] = out[v]
    return out


def _hsl_mod(hex_: str, lum_mod: float, lum_off: float) -> str:
    import colorsys

    r, g, b = (x / 255 for x in _rgb_t(hex_))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.0, min(1.0, l * lum_mod + lum_off))
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return f"{int(round(r * 255)):02X}{int(round(g * 255)):02X}{int(round(b * 255)):02X}"


_PRESET = {"white": "FFFFFF", "black": "000000", "red": "FF0000", "blue": "0000FF", "green": "008000", "gray": "808080", "grey": "808080"}


def _color_choice(el, scheme: dict[str, str]) -> Optional[tuple[str, float]]:
    """(hex, alpha) of an a:srgbClr / a:schemeClr / a:sysClr / a:prstClr element with its lumMod/lumOff/tint/shade."""
    if el is None:
        return None
    kind = _local(el)
    if kind == "srgbClr":
        hex_ = _norm(el.get("val"))
    elif kind == "schemeClr":
        hex_ = scheme.get(el.get("val") or "")
    elif kind == "sysClr":
        hex_ = _norm(el.get("lastClr")) or ("FFFFFF" if el.get("val") == "window" else "000000")
    elif kind == "prstClr":
        hex_ = _PRESET.get((el.get("val") or "").lower())
    else:
        hex_ = None
    if not hex_:
        return None
    alpha = 1.0
    lum_mod, lum_off = 1.0, 0.0
    for m in el:
        name, v = _local(m), m.get("val")
        try:
            f = int(v) / 100000 if v is not None else None
        except ValueError:
            f = None
        if f is None:
            continue
        if name == "alpha":
            alpha = f
        elif name == "lumMod":
            lum_mod = f
        elif name == "lumOff":
            lum_off = f
        elif name == "tint":
            hex_ = _mix(hex_, "FFFFFF", f)
        elif name == "shade":
            hex_ = _mix(hex_, "000000", f)
    if lum_mod != 1.0 or lum_off != 0.0:
        hex_ = _hsl_mod(hex_, lum_mod, lum_off)
    return hex_, alpha


def _fill_color(holder, scheme: dict[str, str], part=None, region=None) -> Optional[str]:
    """Visible colour of the fill inside `holder` (spPr / bgPr): solid, gradient (mean of stops) or picture (mean of
    the region it shows). None for no fill, a mostly transparent fill or an unreadable picture."""
    if holder is None:
        return None
    for child in holder:
        kind = _local(child)
        if kind == "noFill":
            return None
        if kind == "solidFill" and len(child):
            got = _color_choice(child[0], scheme)
            return got[0] if got and got[1] >= 0.5 else None
        if kind == "gradFill":
            stops = [_color_choice(gs[0], scheme) for gs in child.iter(_a("gs")) if len(gs)]
            stops = [s for s in stops if s]
            if not stops or sum(s[1] for s in stops) / len(stops) < 0.5:
                return None
            rgb = [sum(_rgb_t(s[0])[i] for s in stops) / len(stops) for i in range(3)]
            return "".join(f"{int(round(x)):02X}" for x in rgb)
        if kind == "pattFill":
            # a pattern reads as the blend of its two colours (half and half: the density is not modelled)
            fg, bg = child.find(_a("fgClr")), child.find(_a("bgClr"))
            cf = _color_choice(fg[0], scheme) if fg is not None and len(fg) else None
            cb = _color_choice(bg[0], scheme) if bg is not None and len(bg) else None
            if cf and cb:
                return _mix(cf[0], cb[0], 0.5)
            return (cf or cb or (None,))[0]
        if kind == "blipFill" and part is not None:
            blip = child.find(_a("blip"))
            rid = blip.get(f"{{{_R}}}embed") if blip is not None else None
            if rid:
                return _picture_mean(part, rid, region)
    return None


def _picture_mean(part, rid: str, region=None) -> Optional[str]:
    """Mean colour of a picture (over white where transparent), restricted to `region` = (x0, y0, x1, y1) fractions."""
    try:
        from PIL import Image

        blob = part.related_part(rid).blob
        im = Image.open(io.BytesIO(blob))
        im.draft("RGB", (256, 256))
        im = im.convert("RGBA")
        w, h = im.size
        if region:
            x0, y0, x1, y1 = (max(0.0, min(1.0, v)) for v in region)
            if x1 - x0 > 0.01 and y1 - y0 > 0.01:
                im = im.crop((int(x0 * w), int(y0 * h), max(int(x0 * w) + 1, int(x1 * w)), max(int(y0 * h) + 1, int(y1 * h))))
        im = im.resize((24, 24))
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        px = list(bg.convert("RGB").getdata())
        rgb = [sum(p[i] for p in px) / len(px) for i in range(3)]
        return "".join(f"{int(round(x)):02X}" for x in rgb)
    except Exception:  # noqa: BLE001
        return None


def _slide_size(slide: Slide) -> tuple[int, int]:
    try:
        prs = slide.part.package.presentation_part.presentation
        return int(prs.slide_width), int(prs.slide_height)
    except Exception:  # noqa: BLE001
        return 12192000, 6858000


def slide_ground(slide: Slide, bbox: Bbox) -> Optional[str]:
    """The colour a chart at `bbox` sits on: the topmost filled shape or picture under it that covers most of it,
    else the slide / layout / master background (solid, gradient or picture, resolved through the theme)."""
    scheme = _theme_scheme(slide)
    sw, sh = _slide_size(slide)
    cx, cy = bbox.x + bbox.w / 2, bbox.y + bbox.h / 2
    area = max(bbox.w * bbox.h, 1)
    try:
        shapes = list(slide.shapes)
    except Exception:  # noqa: BLE001
        shapes = []
    for shp in reversed(shapes):
        el = shp._element
        kind = _local(el)
        if kind not in ("sp", "pic"):
            continue
        x, y, w, h = shp.left, shp.top, shp.width, shp.height
        if None in (x, y, w, h) or w <= 0 or h <= 0 or not (x <= cx <= x + w and y <= cy <= y + h):
            continue
        ox = max(0, min(x + w, bbox.x + bbox.w) - max(x, bbox.x))
        oy = max(0, min(y + h, bbox.y + bbox.h) - max(y, bbox.y))
        if ox * oy < 0.5 * area:
            continue
        region = ((bbox.x - x) / w, (bbox.y - y) / h, (bbox.x + bbox.w - x) / w, (bbox.y + bbox.h - y) / h)
        sppr = el.find(f"{{{_P}}}spPr")
        if kind == "pic":
            bf = el.find(f"{{{_P}}}blipFill")
            blip = bf.find(_a("blip")) if bf is not None else None
            rid = blip.get(f"{{{_R}}}embed") if blip is not None else None
            got = _picture_mean(slide.part, rid, region) if rid else None
        else:
            got = _fill_color(sppr, scheme, slide.part, region)
            if got is None and sppr is not None and not any(_local(c) in ("noFill", "solidFill", "gradFill", "blipFill", "pattFill") for c in sppr):
                ref = el.find(f"{{{_P}}}style/{_a('fillRef')}")
                if ref is not None and ref.get("idx") not in (None, "0") and len(ref):
                    cc = _color_choice(ref[0], scheme)
                    got = cc[0] if cc and cc[1] >= 0.5 else None
        if got:
            return got
    # what the layout and the master paint under the box (a band, a panel, a full-bleed picture), topmost first
    got = _template_ground(slide, bbox, scheme)
    if got:
        return got
    region = (bbox.x / sw, bbox.y / sh, (bbox.x + bbox.w) / sw, (bbox.y + bbox.h) / sh)
    holders = []
    try:
        holders = [(slide._element, slide.part), (slide.slide_layout._element, slide.slide_layout.part), (slide.slide_layout.slide_master._element, slide.slide_layout.slide_master.part)]
    except Exception:  # noqa: BLE001
        holders = [(slide._element, slide.part)]
    for el, part in holders:
        bg = el.find(f"{{{_P}}}cSld/{{{_P}}}bg")
        if bg is None:
            continue
        pr = bg.find(f"{{{_P}}}bgPr")
        if pr is not None:
            got = _fill_color(pr, scheme, part, region)
            if got:
                return got
            continue
        ref = bg.find(f"{{{_P}}}bgRef")
        if ref is not None and len(ref):
            cc = _color_choice(ref[0], scheme)
            if cc:
                return cc[0]
    return scheme.get("bg1") or None


_OWN_PARTS: "weakref.WeakSet" = weakref.WeakSet()
_TEMPLATE_COLORS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _template_ground(slide: Slide, bbox: Bbox, scheme: dict[str, str]) -> Optional[str]:
    """The colour the slide's layout (then its master, unless a showMasterSp="0" hides it) paints under `bbox`: the
    topmost non-placeholder shape or picture that holds the box's centre and covers half of it (contract C4)."""
    cx, cy = bbox.x + bbox.w / 2, bbox.y + bbox.h / 2
    area = max(bbox.w * bbox.h, 1)
    try:
        layout = slide.slide_layout
        holders = [layout]
        hide = slide._element.get("showMasterSp") == "0" or layout._element.get("showMasterSp") == "0"
        if not hide:
            holders.append(layout.slide_master)
    except Exception:  # noqa: BLE001
        return None
    for holder in holders:
        tree = holder._element.find(f"{{{_P}}}cSld/{{{_P}}}spTree")
        if tree is None:
            continue
        for el in reversed(list(tree)):
            kind = _local(el)
            if kind not in ("sp", "pic") or el.find(f".//{{{_P}}}ph") is not None:
                continue
            sppr = el.find(f"{{{_P}}}spPr")
            xfrm = sppr.find(_a("xfrm")) if sppr is not None else None
            off = xfrm.find(_a("off")) if xfrm is not None else None
            ext = xfrm.find(_a("ext")) if xfrm is not None else None
            if off is None or ext is None:
                continue
            try:
                x, y, w, h = int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy"))
            except (TypeError, ValueError):
                continue
            if w <= 0 or h <= 0 or not (x <= cx <= x + w and y <= cy <= y + h):
                continue
            ox = max(0, min(x + w, bbox.x + bbox.w) - max(x, bbox.x))
            oy = max(0, min(y + h, bbox.y + bbox.h) - max(y, bbox.y))
            if ox * oy < 0.5 * area:
                continue
            region = ((bbox.x - x) / w, (bbox.y - y) / h, (bbox.x + bbox.w - x) / w, (bbox.y + bbox.h - y) / h)
            if kind == "pic":
                bf = el.find(f"{{{_P}}}blipFill")
                blip = bf.find(_a("blip")) if bf is not None else None
                rid = blip.get(f"{{{_R}}}embed") if blip is not None else None
                got = _picture_mean(holder.part, rid, region) if rid else None
            else:
                got = _fill_color(sppr, scheme, holder.part, region)
                if got is None and sppr is not None and not any(_local(c) in ("noFill", "solidFill", "gradFill", "blipFill", "pattFill") for c in sppr):
                    ref = el.find(f"{{{_P}}}style/{_a('fillRef')}")
                    if ref is not None and ref.get("idx") not in (None, "0") and len(ref):
                        cc = _color_choice(ref[0], scheme)
                        got = cc[0] if cc and cc[1] >= 0.5 else None
            if got:
                return got
    return None


def template_chart_colors(slide: Slide) -> list[str]:
    """Series colours of the template's own chart parts, in order: fills (or line colours) given as schemeClr and
    resolved through the theme, or as srgbClr. Charts this module made are skipped."""
    try:
        pkg = slide.part.package
    except Exception:  # noqa: BLE001
        return []
    cached = _TEMPLATE_COLORS.get(pkg)
    if cached is not None:
        return list(cached)
    scheme = _theme_scheme(slide)
    out: list[str] = []
    try:
        parts = list(pkg.iter_parts())
    except Exception:  # noqa: BLE001
        parts = []
    for part in parts:
        if part.content_type != CT.DML_CHART or part in _OWN_PARTS:
            continue
        try:
            root = part._element if hasattr(part, "_element") else etree.fromstring(part.blob)
        except Exception:  # noqa: BLE001
            continue
        for ser in root.iter(_c("ser")):
            sp = ser.find(_c("spPr"))
            if sp is None:
                continue
            fill = sp.find(_a("solidFill"))
            if fill is None:
                fill = sp.find(f"{_a('ln')}/{_a('solidFill')}")
            if fill is None or not len(fill):
                continue
            got = _color_choice(fill[0], scheme)
            if got and got[0] not in out:
                out.append(got[0])
    _TEMPLATE_COLORS[pkg] = list(out)
    return out


def _theme_accents(slide: Slide) -> list[str]:
    scheme = _theme_scheme(slide)
    return [scheme[k] for k in ("accent1", "accent2", "accent3", "accent4", "accent5", "accent6") if k in scheme]


# ---------------------------------------------------------------------------------------------- numbers & units


def number_format(unit: Optional[str]) -> str:
    u = (unit or "").strip()
    if u == "%":
        return '0"%"'
    if u in ("₽", "руб", "руб.", "RUB"):
        return '#,##0" ₽"'
    if u in ("$", "USD"):
        return '"$"#,##0'
    if u:
        return f'#,##0" {u}"'
    return "#,##0"


_UNIT_STOP = {"в", "на", "за", "per", "/", "в/", "за/", "от", "по"}
_GLYPH_UNITS = {"%", "₽", "$", "€", "руб", "руб.", "RUB", "USD", "EUR"}


def short_unit(unit: Optional[str], limit: int = 7) -> str:
    """The unit as a label suffix: «тыс. обращений» → «тыс.», «млн ₽ в год» → «млн ₽». The full unit belongs in
    one caption (see `unit_caption`), never on every label."""
    u = " ".join((unit or "").split())
    if len(u) <= limit:
        return u
    toks = u.split(" ")
    out = toks[0]
    for tok in toks[1:]:
        if tok.lower() in _UNIT_STOP or len(out) + 1 + len(tok) > limit:
            break
        out = f"{out} {tok}"
    return out


def glyph_unit(unit: Optional[str]) -> bool:
    """A one-glyph unit (%, ₽, $, €) rides on every label; a word unit is written once."""
    u = " ".join((unit or "").split())
    return u in _GLYPH_UNITS or short_unit(u) in _GLYPH_UNITS


def unit_caption(spec: ChartSpec, outline: DeckOutline) -> Optional[str]:
    """A word unit («тыс. обращений», «чел.») for a caption placed once above the chart, so that every label is a
    plain number of one scale (a unit on one label only reads as «12 against 58 thousand»). One-glyph units (%, ₽)
    ride on the labels and need no caption. A chart whose caller puts this text right above it (or in its title)
    writes no unit caption of its own."""
    if spec.type in ("pie", "doughnut"):
        return None
    series = resolve_series(spec, outline)
    if not series:
        return None  # no chart, no caption: a unit over an empty frame is a stray word
    unit = spec.unit or series[0].unit
    u = " ".join((unit or "").split())
    return u if u and not glyph_unit(u) else None


def _decimals(values: Iterable[Optional[float]]) -> int:
    vals = [abs(float(v)) for v in values if v is not None]
    if not vals or all(abs(v - round(v)) < 1e-6 for v in vals):
        return 0
    mx = max(vals)
    if mx >= 100:
        return 0
    if mx < 10 and any(abs(v * 10 - round(v * 10)) > 1e-6 for v in vals):
        return 2
    return 1


def _unit_affix(unit: Optional[str]) -> tuple[str, str]:
    u = short_unit(unit)
    if not u:
        return "", ""
    if u == "%":
        return "", "%"
    if u in ("₽", "руб", "руб.", "RUB"):
        return "", " ₽"
    if u in ("$", "USD"):
        return "$", ""
    if u in ("€", "EUR"):
        return "", " €"
    return "", f" {u}"


def label_format(unit: Optional[str], values: Iterable[Optional[float]] = ()) -> str:
    """Excel number format for data labels: thousands grouped, decimals only when the data has them, the short unit
    as a suffix (non-breaking, so a label never wraps), and an empty zero section so a zero prints nothing."""
    d = _decimals(values)
    u = short_unit(unit)
    num = ("0" if u == "%" else "#,##0") + ("." + "0" * d if d else "")
    pre, suf = _unit_affix(unit)
    q = lambda s: f'"{s}"' if s else ""  # noqa: E731
    pos = f"{q(pre)}{num}{q(suf)}"
    return f'{pos};"−"{pos};'  # a true minus sign, and an empty zero section


def _tick_format(unit: Optional[str], decimals: int) -> str:
    """Value-axis ticks: plain numbers; only a one-glyph unit (%, ₽, $) rides along — words never repeat per tick."""
    num = "#,##0" + ("." + "0" * decimals if decimals else "")
    u = short_unit(unit)
    if u == "%":
        return num + '"%"'
    if u in ("₽", "руб", "руб.", "RUB"):
        return num + '" ₽"'
    if u in ("$", "USD"):
        return '"$"' + num
    return num


def _fmt_value(v: Optional[float], unit: Optional[str], decimals: int) -> str:
    """What a label prints (for measuring): 12 400 чел., 4,8 %."""
    if v is None or v == 0:
        return ""
    s = f"{abs(v):,.{decimals}f}".replace(",", " ").replace(".", ",")
    pre, suf = _unit_affix(unit)
    sign = "−" if v < 0 else ""
    return f"{sign}{pre}{s}{suf}"


def _nice_scale(lo: float, hi: float) -> tuple[float, float, float]:
    """(min, max, major unit) of a quiet value axis: a round step giving 4–5 intervals, the ends snapped to it."""
    if hi <= lo:
        hi = lo + (abs(lo) or 1.0)
    best = None
    mag = 10 ** math.floor(math.log10((hi - lo) / 4.5))
    for m in (0.1, 1, 10):
        for base in (1, 2, 2.5, 5):
            step = base * mag * m
            a = math.floor(lo / step + 1e-9) * step
            b = math.ceil(hi / step - 1e-9) * step
            k = round((b - a) / step)
            if k < 3 or k > 7:
                continue
            cost = abs(k - 4.5) + (0.3 if base == 2.5 else 0.0)
            if best is None or cost < best[0]:
                best = (cost, a, b, step)
    if best is None:
        return lo, hi, (hi - lo) / 4
    _, a, b, step = best
    return a, b, step


# ---------------------------------------------------------------------------------------------- decisions


def inline_series(spec: ChartSpec) -> list[Series]:
    """The data the slide designer wrote into the chart itself (Agent v2: `categories` + `series`), as registry-like
    Series: values cut to the categories, a missing tail padded with None; series without a value are left out."""
    cats = [str(c) for c in (spec.categories or []) if str(c).strip()]
    if not cats:
        return []
    out: list[Series] = []
    for i, s in enumerate(spec.series or []):
        vals = [(float(v) if v is not None else None) for v in list(s.values or [])[: len(cats)]]
        if not any(v is not None for v in vals):
            continue
        name = (s.name or spec.title or "").strip()
        if len(vals) == len(cats) and all(v is not None for v in vals):
            out.append(Series(id=f"inline_{i + 1}", name=name, categories=cats, values=vals, unit=spec.unit))
        else:  # a short series: its missing tail is a gap in the chart, not a zero
            vals += [None] * (len(cats) - len(vals))
            out.append(Series.model_construct(id=f"inline_{i + 1}", name=name, categories=cats, values=vals, unit=spec.unit, source_span=None))
    return out


def resolve_series(spec: ChartSpec, outline: DeckOutline) -> list[Series]:
    """The series a chart draws: the registry series its ids name; else the data written into the chart itself
    (`categories` + `series`); else — ids that name nothing and no data of its own — the deck's first series, unless
    the ids name facts: a chart «of f1, f2» asks for those figures, and another series of the deck would be someone
    else's data."""
    out = [s for sid in spec.series_ids if (s := outline.series_by_id(sid)) is not None]
    if not out:
        out = inline_series(spec)
    if not out and outline.series and not (spec.categories or spec.series) and not any(outline.fact_by_id(sid) is not None for sid in spec.series_ids):
        out = outline.series[:1]
    return out


def chart_data_ok(spec: Optional[ChartSpec], outline: DeckOutline) -> bool:
    """True when `add_chart` has something to draw: a series with categories and at least one value."""
    if spec is None:
        return False
    series = resolve_series(spec, outline)
    if not series or not series[0].categories:
        return False
    n = len(series[0].categories)
    return any(v is not None for s in series for v in list(s.values)[:n])


def prefer_bar(spec: ChartSpec, outline: DeckOutline) -> bool:
    """A bar/column chart reads better as horizontal bars: a category label longer than 12 characters, or more than 7
    categories (short labels such as years or quarters fit columns up to 12)."""
    if spec.type not in ("column", "bar"):
        return False
    if spec.type == "bar":
        return True
    series = resolve_series(spec, outline)
    if not series:
        return False
    cats = [str(c) for c in series[0].categories]
    longest = max((len(c.strip()) for c in cats), default=0)
    # two columns (before / after) are wide: a label of a few words wraps under its column in two lines
    if longest > (PAIR_LABEL_CHARS if len(cats) <= 2 else LONG_LABEL_CHARS):
        return True
    return len(cats) > MAX_COLUMNS and (longest > 5 or len(cats) > 12)


def effective_chart_type(spec: ChartSpec, outline: DeckOutline) -> str:
    return "bar" if prefer_bar(spec, outline) else (spec.type if spec.type in _TYPE_MAP else "column")


_OTHER_RE = re.compile(r"^\s*(проч|други|другое|остальн|ины[ея]|иное|other|rest\b|misc)", re.I)
_PLAN_RE = re.compile(r"(план|цел[ьи]\b|прогноз|ожидан|таргет|target|plan\b|goal|forecast|budget|бюджет)", re.I)
_NOW_RE = re.compile(r"(стало|после|факт|сейчас|текущ|\bнов|\bwith\b|after|actual|\bnow\b|current)", re.I)
_PAST_RE = re.compile(r"(было|\bдо\b|\bбез\b|прошл|стар|without|before|previous|prior|baseline|базов)", re.I)
_YEAR_RE = re.compile(r"(?<!\d)(19\d\d|20\d\d)(?!\d)")


_MONTH_SHORT = {
    "январ": "янв", "феврал": "фев", "март": "мар", "апрел": "апр", "июн": "июн", "июл": "июл",
    "август": "авг", "сентябр": "сен", "октябр": "окт", "ноябр": "ноя", "декабр": "дек",
}
_PERIOD_WORDS = (
    (re.compile(r"(?i)\bмесяц(?:а|ев|ы)?\b"), "мес."),
    (re.compile(r"(?i)\bквартал(?:а|ов|ы)?\b"), "кв."),
    (re.compile(r"(?i)\bнедел(?:я|и|ь)\b"), "нед."),
    (re.compile(r"(?i)\bполугоди(?:е|я)\b"), "полуг."),
)
_MONTH_WORD_RE = re.compile(r"(?i)\b(январ|феврал|март|апрел|ма|июн|июл|август|сентябр|октябр|ноябр|декабр)[а-яё]*\b")


def short_categories(cats: Sequence[str], joiner: bool = True) -> list[str]:
    """Category labels of a time axis set short, for a chart whose slots are too narrow for them: «1-й месяц» →
    «1-й мес.», «Месяц 3» → «Мес. 3», «Январь 2026» → «Янв 2026», «2 квартал» → «2 кв.». Only the period words are
    shortened (the figures and the other words stay), and only in the chart: the plan keeps its words. `joiner=False`:
    no word joiner after a hyphen (U+2060 is not rendered by every reader: a box or a break instead of nothing)."""
    out = []
    for c in cats:
        t = " ".join(str(c).split())
        for rx, rep in _PERIOD_WORDS:
            t = rx.sub(lambda m, rep=rep: rep if m.group(0)[:1].islower() else rep[:1].upper() + rep[1:], t)

        def month(m: re.Match) -> str:
            word = m.group(0)
            if m.group(1).lower() == "ма":
                return word  # «май», «мая» are short already («март» is caught above; «макет» is no month)
            short = _MONTH_SHORT.get(m.group(1).lower(), word)
            return short[:1].upper() + short[1:] if word[:1].isupper() else short

        t = _MONTH_WORD_RE.sub(month, t)
        # a shortened label is one word for the renderer: «1-й мес.» never breaks after «1-» or «1-й»
        if t != " ".join(str(c).split()):
            t = t.replace(" ", "\u00a0")
            if joiner:
                t = t.replace("-", "-\u2060")
        out.append(t)
    return out


def is_other_category(name: str) -> bool:
    """«Прочее», «Другие», «Other»: a remainder slice, coloured quietly rather than as a category of its own."""
    return bool(_OTHER_RE.match(name or ""))


def series_roles(names: Sequence[str]) -> Optional[list[str]]:
    """The story several series tell, from their names: «lead» (the latest / actual: Стало, После, Факт, the last
    year), «past» (Было, До, earlier years) and «plan» (План, Цель, Прогноз). None when the names tell no such story
    (Web / Mobile): those series keep distinct categorical colours."""
    k = len(names)
    if k < 2:
        return None
    roles: list[Optional[str]] = [None] * k
    for i, nm in enumerate(names):
        if _PLAN_RE.search(nm or ""):
            roles[i] = "plan"
    years = {i: int(m.group(1)) for i, nm in enumerate(names) if roles[i] is None and (m := _YEAR_RE.search(nm or ""))}
    if len(set(years.values())) >= 2:
        latest = max(years, key=lambda i: (years[i], i))
        for i in years:
            roles[i] = "lead" if i == latest else "past"
    for i, nm in enumerate(names):
        if roles[i] is None:
            if _NOW_RE.search(nm or ""):
                roles[i] = "lead"
            elif _PAST_RE.search(nm or ""):
                roles[i] = "past"
    if not any(r in ("past", "plan") for r in roles):
        return None
    leads = [i for i, r in enumerate(roles) if r == "lead"]
    free = [i for i, r in enumerate(roles) if r is None]
    if not leads and len(free) == 1:
        roles[free[0]] = "lead"  # «Выручка» next to «План»
        leads, free = free, []
    if len(leads) != 1 or free:
        return None
    return roles  # type: ignore[return-value]


_AX_TAGS = ("axId", "crossAx")
_AX_ID_BASE = 510_000_000  # well inside int32: LibreOffice reads axis ids as signed 32-bit and loses larger ones


def fix_axis_ids(chart_space) -> None:
    """python-pptx writes negative axis ids (-2068027336); the schema wants xs:unsignedInt, and LibreOffice reads them
    as signed 32-bit (an id ≥ 2^31 loses the axis pairing: no category labels, gridlines on the wrong axis). Every id
    is mapped to a small positive one consistently, so c:axId / c:crossAx pairs keep pointing at each other."""
    mapping: dict[str, str] = {}
    for el in chart_space.iter(*(_c(t) for t in _AX_TAGS)):
        v = el.get("val")
        if v is None:
            continue
        if v not in mapping:
            mapping[v] = str(_AX_ID_BASE + len(mapping) + 1)
        el.set("val", mapping[v])


# ---------------------------------------------------------------------------------------------- XML builders


def _insert_before(parent, new, successors: Sequence[str]) -> None:
    """Insert `new` before the first child whose local name is in `successors` (the schema order), else append."""
    for child in parent:
        if _local(child) in successors:
            child.addprevious(new)
            return
    parent.append(new)


def _replace(parent, tag: str, new, successors: Sequence[str]) -> None:
    old = parent.find(_c(tag))
    if old is not None:
        old.addprevious(new)
        parent.remove(old)
    else:
        _insert_before(parent, new, successors)


def _txpr(size: float, color: Optional[str] = None, bold: Optional[bool] = None, family: Optional[str] = None, horizontal: bool = False, nowrap: bool = False):
    tx = etree.Element(_c("txPr"))
    bp = etree.SubElement(tx, _a("bodyPr"))
    if nowrap:
        bp.set("wrap", "none")
    if horizontal:
        bp.set("rot", "0")
        bp.set("vert", "horz")
    etree.SubElement(tx, _a("lstStyle"))
    p = etree.SubElement(tx, _a("p"))
    ppr = etree.SubElement(p, _a("pPr"))
    d = etree.SubElement(ppr, _a("defRPr"))
    d.set("sz", str(int(round(size * 100))))
    if bold is not None:
        d.set("b", "1" if bold else "0")
    if color:
        sf = etree.SubElement(d, _a("solidFill"))
        etree.SubElement(sf, _a("srgbClr")).set("val", color)
    if family:
        for tag in ("latin", "ea", "cs"):
            etree.SubElement(d, _a(tag)).set("typeface", family)
    etree.SubElement(p, _a("endParaRPr")).set("lang", "ru-RU")
    return tx


def _fonts_everywhere(chart_space, family: Optional[str]) -> None:
    """Every run property that names a latin typeface names the same ea and cs typefaces (schema order latin, ea, cs),
    so no script falls back to the theme font."""
    if not family:
        return
    for latin in list(chart_space.iter(_a("latin"))):
        parent = latin.getparent()
        prev = latin
        for tag in ("ea", "cs"):
            el = parent.find(_a(tag))
            if el is None:
                el = etree.Element(_a(tag))
                el.set("typeface", latin.get("typeface") or family)
                prev.addnext(el)
            prev = el


def _sppr(fill: Optional[str] = None, alpha: Optional[float] = None, line: Optional[str] = None, line_w: Optional[float] = None, no_line: bool = True, dash: Optional[str] = None):
    sp = etree.Element(_c("spPr"))
    if fill:
        sf = etree.SubElement(sp, _a("solidFill"))
        clr = etree.SubElement(sf, _a("srgbClr"))
        clr.set("val", fill)
        if alpha is not None and alpha < 1:
            etree.SubElement(clr, _a("alpha")).set("val", str(int(alpha * 100000)))
    else:
        etree.SubElement(sp, _a("noFill"))
    if line:
        ln = etree.SubElement(sp, _a("ln"))
        ln.set("w", str(int((line_w or 0.75) * EMU_PER_PT)))
        ln.set("cap", "rnd")
        sf = etree.SubElement(ln, _a("solidFill"))
        etree.SubElement(sf, _a("srgbClr")).set("val", line)
        if dash:
            etree.SubElement(ln, _a("prstDash")).set("val", dash)
        etree.SubElement(ln, _a("round"))
    elif no_line:
        ln = etree.SubElement(sp, _a("ln"))
        etree.SubElement(ln, _a("noFill"))
    return sp


_DLBL_TAIL = ("showLegendKey", "showVal", "showCatName", "showSerName", "showPercent", "showBubbleSize")
_SER_AFTER_DLBLS = ("trendline", "errBars", "cat", "val", "smooth", "shape", "extLst")


def _flags(parent, show_val: bool = True, leader_lines: Optional[bool] = None, ser_name: bool = False, sep: Optional[str] = None) -> None:
    for tag in _DLBL_TAIL:
        on = (tag == "showVal" and show_val) or (tag == "showSerName" and ser_name)
        etree.SubElement(parent, _c(tag)).set("val", "1" if on else "0")
    if sep is not None:
        etree.SubElement(parent, _c("separator")).text = sep
    if leader_lines is not None:
        etree.SubElement(parent, _c("showLeaderLines")).set("val", "1" if leader_lines else "0")


def _dlbls(fmt: str, size: float, color: str, family: Optional[str], pos: Optional[str], points: Optional[dict] = None, leader_lines: Optional[bool] = False, bold: bool = False, show_val: bool = True):
    """A complete c:dLbls: per-point overrides (`points[idx]` = {"delete": True} or any of "fmt", "size", "color",
    "bold", "pos", "dx"/"dy" (a nudge, as a fraction of the chart frame), "sername" (series name + value)), then the
    shared numFmt, transparent box, text, position and flags. Leader lines are off: a nudged label is never tied to
    its point by a stray line."""
    d = etree.Element(_c("dLbls"))
    for idx in sorted(points or {}):
        o = points[idx]
        lbl = etree.SubElement(d, _c("dLbl"))
        etree.SubElement(lbl, _c("idx")).set("val", str(idx))
        if o.get("delete"):
            etree.SubElement(lbl, _c("delete")).set("val", "1")
            continue
        if o.get("dx") or o.get("dy"):
            lay = etree.SubElement(lbl, _c("layout"))
            ml = etree.SubElement(lay, _c("manualLayout"))
            etree.SubElement(ml, _c("x")).set("val", f"{o.get('dx', 0.0):.4f}")
            etree.SubElement(ml, _c("y")).set("val", f"{o.get('dy', 0.0):.4f}")
        nf = etree.SubElement(lbl, _c("numFmt"))
        nf.set("formatCode", o.get("fmt", fmt))
        nf.set("sourceLinked", "0")
        lbl.append(_sppr())
        lbl.append(_txpr(o.get("size", size), o.get("color", color), o.get("bold", bold), family, nowrap=True))
        p = o.get("pos", pos)
        if p:
            etree.SubElement(lbl, _c("dLblPos")).set("val", p)
        _flags(lbl, ser_name=bool(o.get("sername")), sep=LABEL_SEP if o.get("sername") else None)
    nf = etree.SubElement(d, _c("numFmt"))
    nf.set("formatCode", fmt)
    nf.set("sourceLinked", "0")
    d.append(_sppr())
    d.append(_txpr(size, color, bold, family, nowrap=True))
    if pos:
        etree.SubElement(d, _c("dLblPos")).set("val", pos)
    _flags(d, show_val=show_val, leader_lines=leader_lines)
    return d


def _set_ser_dlbls(ser_el, dlbls) -> None:
    old = ser_el.find(_c("dLbls"))
    if old is not None:
        ser_el.remove(old)
    _insert_before(ser_el, dlbls, _SER_AFTER_DLBLS)


def _set_plot_dlbls(chart_el, dlbls) -> None:
    """The chart-type level c:dLbls (read by the audit and by editors as the series default)."""
    old = chart_el.find(_c("dLbls"))
    if old is not None:
        old.addprevious(dlbls)
        chart_el.remove(old)
        return
    _insert_before(chart_el, dlbls, ("gapWidth", "overlap", "serLines", "dropLines", "hiLowLines", "upDownBars", "marker", "smooth", "firstSliceAng", "holeSize", "axId", "extLst"))


def _manual_layout(holder, x: float, y: float, w: Optional[float], h: Optional[float], inner: bool = True) -> None:
    layout = holder.find(_c("layout"))
    if layout is None:
        layout = etree.Element(_c("layout"))
        holder.insert(0, layout) if _local(holder) == "plotArea" else _insert_before(holder, layout, ("overlay", "spPr", "txPr", "extLst"))
    for child in list(layout):
        layout.remove(child)
    ml = etree.SubElement(layout, _c("manualLayout"))
    items = ([("layoutTarget", "inner")] if inner else []) + [("xMode", "edge"), ("yMode", "edge")]
    x, y = max(0.0, min(0.95, x)), max(0.0, min(0.95, y))
    items += [("x", f"{x:.4f}"), ("y", f"{y:.4f}")]
    if w is not None and h is not None:
        w, h = max(0.05, min(1.0 - x, w)), max(0.05, min(1.0 - y, h))
        items += [("w", f"{w:.4f}"), ("h", f"{h:.4f}")]
    for tag, val in items:
        etree.SubElement(ml, _c(tag)).set("val", val)


def _transparent(chart) -> None:
    """No white box behind the chart: chart space and plot area without fill or border, square corners."""
    cs = chart._chartSpace
    for holder in (cs, cs.find(f".//{_c('plotArea')}")):
        if holder is None:
            continue
        sp = holder.find(_c("spPr"))
        if sp is None:
            sp = etree.Element(_c("spPr"))
            if holder is cs:
                chart_el = holder.find(_c("chart"))
                if chart_el is not None:
                    chart_el.addnext(sp)
                else:
                    holder.append(sp)
            else:
                _insert_before(holder, sp, ("extLst",))
        for child in list(sp):
            sp.remove(child)
        etree.SubElement(sp, _a("noFill"))
        ln = etree.SubElement(sp, _a("ln"))
        etree.SubElement(ln, _a("noFill"))
    if cs.find(_c("roundedCorners")) is None:
        rc = etree.Element(_c("roundedCorners"))
        rc.set("val", "0")
        _insert_before(cs, rc, ("AlternateContent", "clrMapOvr", "pivotSource", "protection", "chart"))


def _axis_txpr(axis, size: float, color: str, family: Optional[str]) -> None:
    el = axis._element
    _replace(el, "txPr", _txpr(size, color, False, family, horizontal=True), ("crossAx", "crosses", "crossesAt", "crossBetween", "auto", "lblAlgn", "lblOffset", "extLst"))


def _set_child_val(parent, tag: str, val: str, successors: Sequence[str]) -> None:
    el = parent.find(_c(tag))
    if el is None:
        el = etree.Element(_c(tag))
        _insert_before(parent, el, successors)
    el.set("val", val)


def _snap(v: float) -> float:
    return round(v * 2) / 2


# ---------------------------------------------------------------------------------------------- ring


def add_ring(slide: Slide, bbox: Bbox, percent: float, color_hex: str, ground_hex: Optional[str] = None):
    """A native doughnut showing `percent` — the true value in place of a ring drawn as a picture. The track is a
    faint tint of the colour over the ground; no legend, no labels (the figure sits in the hole), transparent back."""
    percent = max(0.0, min(100.0, percent))
    data = CategoryChartData()
    data.categories = ["value", "rest"]
    data.add_series("share", (percent, 100.0 - percent))
    gf = slide.shapes.add_chart(XL_CHART_TYPE.DOUGHNUT, Emu(bbox.x), Emu(bbox.y), Emu(bbox.w), Emu(bbox.h), data)
    _OWN_PARTS.add(gf.chart_part)
    chart = gf.chart
    chart.has_legend = False
    chart.has_title = False
    plot = chart.plots[0]
    plot.has_data_labels = False
    track = _mix(color_hex, ground_hex or "FFFFFF", 0.14)
    for j, pt in enumerate(plot.series[0].points):
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = _rgb(color_hex if j == 0 else track)
        pt.format.line.fill.background()
    dn = chart._chartSpace.find(f".//{_c('doughnutChart')}")
    if dn is not None:
        for tag, val in (("firstSliceAng", "0"), ("holeSize", "78")):
            el = dn.find(_c(tag))
            if el is not None:
                el.set("val", val)
    # the ring fills its frame, centred: the figure placed in the middle of the frame sits in the hole
    plot_area = chart._chartSpace.find(f".//{_c('plotArea')}")
    if plot_area is not None:
        _manual_layout(plot_area, 0.02, 0.02, 0.96, 0.96)
    _transparent(chart)
    return gf


# ---------------------------------------------------------------------------------------------- type from the template


def _font_floor(slide: Slide) -> float:
    """The smallest chart text, relative to the slide: 2 % of its height (≈ 11 pt on a 16:9 slide of 540 pt, 8 pt on
    one of 405 pt, where the template's 9 pt body is the same size on screen)."""
    _, sh = _slide_size(slide)
    return max(8.0, 0.02 * sh / EMU_PER_PT)


def _type_sizes(typography: Optional[Typography], used: bool = False) -> list[float]:
    """The template's type scale (role sizes); with `used`, also every other whole or half size it sets."""
    if typography is None:
        return []
    sizes = {_snap(s.size_pt) for s in (typography.scale or []) if s.size_pt and s.size_pt > 0}
    if used:
        sizes |= {_snap(v) for v in (typography.sizes_used or []) if v and abs(v * 2 - round(v * 2)) < 0.05}
    return sorted(sizes)


def _size_at_least(size: float, typography: Optional[Typography], cap: float = 1.4) -> float:
    """The smallest template size ≥ `size` (and not above `cap` × it): a role size of the type scale when one is
    near, else another size the template uses, else `size` itself rounded to half a point."""
    for pool in (_type_sizes(typography), _type_sizes(typography, used=True)):
        near = [s for s in pool if size - 0.05 <= s <= size * cap]
        if near:
            return min(near)
    return _snap(size)


def _size_at_most(size: float, typography: Optional[Typography], floor: float = 0.8) -> float:
    """The largest template size ≤ `size` (and not under `floor` × it), else `size` itself rounded down to half a
    point."""
    pool = [s for s in _type_sizes(typography, used=True) if size * floor - 0.05 <= s <= size + 0.05]
    return max(pool) if pool else math.floor(size * 2) / 2


def chart_text_capped(typography: Optional[Typography], font_size_pt: Optional[float], slide_h_emu: int) -> bool:
    """Chart and table text is capped relative to the slide when the template's own chart text is larger than 2.6 %
    of the slide height (a bullet placeholder's 24 pt taken for chart text) or its type scale is too thin to trust
    (a derived ladder). The dataset templates set 7–12 pt: never capped."""
    hpt = slide_h_emu / EMU_PER_PT if slide_h_emu else 0.0
    sparse = bool(getattr(typography, "derived_sizes", None)) if typography is not None else False
    return sparse or (hpt > 0 and (font_size_pt or 0.0) > 0.026 * hpt)


def _bold_voice(typography: Optional[Typography]) -> bool:
    """Does the template emphasise with weight? Only when its display / h1 are set in bold often enough."""
    if typography is None:
        return False
    return max((s.weight_bold_share for s in (typography.scale or []) if s.role in ("display", "h1")), default=0.0) >= BOLD_VOICE_SHARE


def _unit_shown_above(slide: Slide, bbox: Bbox, unit_full: str) -> bool:
    """The caller already wrote the full unit right above the chart (a caption or a heading ending in it)."""
    u = " ".join(unit_full.split()).lower()
    if not u:
        return False
    _, sh = _slide_size(slide)
    try:
        shapes = list(slide.shapes)
    except Exception:  # noqa: BLE001
        return False
    for shp in shapes:
        if not getattr(shp, "has_text_frame", False) or shp.top is None or shp.height is None:
            continue
        t = " ".join(shp.text_frame.text.replace(" ", " ").split()).lower()
        if not t or u.replace(" ", " ") not in t:
            continue
        bottom = shp.top + shp.height
        overlap = min(shp.left + shp.width, bbox.x + bbox.w) - max(shp.left, bbox.x)
        if overlap > 0 and bbox.y - 0.14 * sh <= bottom <= bbox.y + 0.03 * sh:
            return True
    return False


# ---------------------------------------------------------------------------------------------- charts


@dataclass
class _Kit:
    """Everything the chart-kind stylers share."""

    chart: object
    plot: object
    chart_el: object
    kind: str
    series: list
    values: list
    cats: list
    spec: ChartSpec
    palette: list
    accent: str
    ground: str
    text: str
    muted: str
    rule: str
    fs: float  # category labels, legend, caption
    fs_value: float  # value labels
    fs_hl: float  # the emphasised value label (fs_value when the template emphasises with bold)
    bold: bool  # the template's emphasis is bold
    family: Optional[str]
    fmt_unit: str  # label format with the (short) unit
    fmt_plain: str  # the plain number (keeps a one-glyph unit)
    fmt_emph: str  # the one label that carries the unit (plain when a caption / title / the caller carries it)
    unit: Optional[str]
    unit_plain: Optional[str]  # the unit as the plain labels print it (glyph units only)
    unit_emph: Optional[str]
    decimals: int
    W: float
    H: float
    sw: int
    sh: int
    title_h: float
    legend_h: float = 0.0
    legend_w: float = 0.0
    roles: Optional[list] = None
    styles: list = field(default_factory=list)  # per series: {"fill", "line", "dash", "label"}
    outside: bool = True  # a pie may set a label outside a thin slice (False: the caller's legend carries it)
    slice_labels: bool = True  # a pie of amounts with the caller's legend: no computed shares on the slices
    capped: bool = False  # chart text capped relative to the slide (chart_text_capped): category labels measured strictly
    squeeze: float = 0.0  # a trend chart's longest category label over its slot (> 1: the renderer breaks it inside a word)
    turned: bool = False  # its category labels were turned by 45° or thinned out (every other one blank) to stay whole

    def plain(self, v) -> str:
        return _fmt_value(v, self.unit_plain, self.decimals)

    def emph(self, v) -> str:
        return _fmt_value(v, self.unit_emph, self.decimals)

    @property
    def hl_color(self) -> str:
        return self.accent if contrast_ratio(self.accent, self.ground) >= 3.0 else self.text

    def hl_label(self, size_ratio: float = 1.0) -> dict:
        return {"color": self.hl_color, "bold": self.bold, "size": _snap(self.fs_hl * size_ratio), "fmt": self.fmt_emph}


def _legend(k: _Kit, names: Sequence[str], side: bool) -> None:
    """A bottom (or, for a pie in a wide frame, right-hand) legend in the muted text colour; sets k.legend_h / _w."""
    chart = k.chart
    chart.has_legend = True
    lg = chart.legend
    lg.include_in_layout = False
    lg.position = XL_LEGEND_POSITION.RIGHT if side else XL_LEGEND_POSITION.BOTTOM
    lg.font.size = Pt(k.fs)
    lg.font.color.rgb = _rgb(k.muted)
    if k.family:
        lg.font.name = k.family
    widest = max((text_width_pt(t, k.family, k.fs) for t in names), default=40.0)
    if side:
        k.legend_w = min(widest + k.fs * 2.4, k.W * 0.45)
    else:
        per_row = max(1, int(k.W // (widest + k.fs * 2.6)))
        rows = math.ceil(len(names) / per_row)
        k.legend_h = rows * k.fs * 1.3 + k.fs * 0.9


def _series_styles(k: _Kit) -> list[dict]:
    """Per-series paint. With a story (roles): the latest in the accent, earlier ones in its tints (older = fainter),
    a plan hollow (bars) or dashed (lines); labels of the stepped-back series in the muted text colour. Without: the
    categorical palette."""
    n = len(k.series)
    if not k.roles:
        return [{"fill": k.palette[i % len(k.palette)], "label": k.text, "role": None} for i in range(n)]
    out: list[dict] = [{} for _ in range(n)]
    pasts = [i for i, r in enumerate(k.roles) if r == "past"]
    # the most recent past is the one nearest the lead (years: the latest; words: the later one in the list)
    years = {i: int(m.group(1)) for i in pasts if (m := _YEAR_RE.search(k.series[i].name or ""))}
    pasts.sort(key=lambda i: (years.get(i, 0), i), reverse=True)
    taken = [k.accent]
    for rank, i in enumerate(pasts):
        c = muted_tint(k.accent, k.ground, MUTED_TOWARD_GROUND if rank == 0 else 0.8)
        if any(delta_e(c, t) < MIN_SERIES_DE * 0.75 for t in taken):
            c = next((p for p in k.palette[1:] if all(delta_e(p, t) >= MIN_SERIES_DE for t in taken)), c)
        taken.append(c)
        out[i] = {"fill": c, "label": k.muted, "role": "past"}
    for i, r in enumerate(k.roles):
        if r == "lead":
            out[i] = {"fill": k.accent, "label": k.text, "role": "lead"}
        elif r == "plan":
            out[i] = {"fill": None, "line": k.accent, "label": k.muted, "role": "plan"}
    return out


def add_chart(
    slide: Slide,
    bbox: Bbox,
    spec: ChartSpec,
    outline: DeckOutline,
    style: ChartStyleSpec,
    typography: Typography,
    text_hex: Optional[str] = None,
    neutral_hex: Optional[str] = None,
    *,
    ground_hex: Optional[str] = None,
    accent_hex: Optional[str] = None,
    legend: bool = True,
    amounts: bool = False,
):
    """A native chart at `bbox`, finished to the rules in the module docstring. `amounts` (a pie or a doughnut of
    amounts, not percents, drawn with the caller's legend): the chart keeps the amounts as its data and labels its
    slices with them (the brief's figures) — no computed share is written on a slice as if it were a figure of the
    brief; the caller's legend gives each part's amount and its share, headed as a share. `ground_hex` is the colour
    under the chart (read from the slide when omitted); `accent_hex` overrides accent.1 (the highlight). `legend=False`: a pie
    or a doughnut without its own legend (the caller sets one beside it) — the circle takes the whole frame and a
    slice too thin for its label inside carries none (the caller's legend gives every share)."""
    series = resolve_series(spec, outline)
    if not series:
        raise ValueError("chart has no series data")
    kind = effective_chart_type(spec, outline)
    if kind in ("pie", "doughnut"):
        series = series[:1]
    cats = [str(c) for c in series[0].categories]
    n = len(cats)
    multi = len(series) > 1
    values = [[(float(v) if v is not None else None) for v in list(s.values)[:n]] for s in series]
    unit = spec.unit or series[0].unit

    # --- ground, text and colours
    ground = _norm(ground_hex) or slide_ground(slide, bbox)
    if not ground:
        ground = "000000" if (_norm(text_hex) and not _is_dark(_norm(text_hex)) and relative_luminance(_norm(text_hex)) > 0.5) else "FFFFFF"
    text = _readable_text(text_hex, ground)
    muted = _muted_text(text, ground)
    rule = _rule_color(neutral_hex, text, ground)
    # accent.1 leads; then the template's own chart colours, the theme accents (what Office charts use) and the
    # manifest's ranked fill colours. On a ground the accent cannot stand on (an accent-coloured panel) the text
    # colour takes the lead, as white bars on a brand-blue slide.
    manifest = [c for c in list(style.series_colors or []) if _norm(c)]
    lead = _norm(accent_hex) or (manifest[0] if manifest else None) or "0077FF"
    if contrast_ratio(lead, ground) < MIN_FILL_CONTRAST:
        lead = text
    extra = template_chart_colors(slide) + _theme_accents(slide) + manifest[1:] + ([manifest[0]] if manifest else [])
    others = [j for j, c in enumerate(cats) if is_other_category(c)] if kind in ("pie", "doughnut") and n > 2 else []
    if kind in ("pie", "doughnut"):
        # the largest slice in the accent, the others in its tints (a remainder quiet): one whole, one hue
        shades = pie_shades(values[0], lead, ground, others, text)
        palette = [base if share >= 1.0 else _mix(base, ground, share) for base, share in shades]
        accent = lead
    else:
        palette = chart_palette([lead], ground, max(1, len(series)), extra=extra)
        accent = palette[0]

    # --- type: sizes on the template scale, weight from its voice
    W, H = max(bbox.w, EMU_PER_PT) / EMU_PER_PT, max(bbox.h, EMU_PER_PT) / EMU_PER_PT
    sw, sh = _slide_size(slide)
    family = style.font_family or typography.primary_family
    fs = _size_at_least(max(style.font_size_pt or 0.0, _font_floor(slide)), typography, cap=1.35)
    try:
        body = typography.size_for("body", fs)
    except Exception:  # noqa: BLE001
        body = fs
    # the values speak a step above the category labels, at the template's body size where that is such a step
    fs_value = _size_at_least(max(fs * 1.1, min(body or fs, fs * 1.5)), typography, cap=1.45)
    bold = _bold_voice(typography)
    fs_hl = fs_value if bold else _size_at_least(fs_value * 1.12, typography, cap=1.4)
    capped = chart_text_capped(typography, style.font_size_pt, sh)
    if capped:
        # chart text relative to the slide (≤ 2.6 % of its height) and to its frame (≤ a tenth of it): a bullet
        # placeholder's 24 pt on an 11″ slide is not a chart label size
        hpt = sh / EMU_PER_PT
        cap = max(min(0.026 * hpt, H / 10.0), 8.0)
        if fs > cap:
            fs = _size_at_most(cap, typography)
        fs_value = max(fs, _size_at_most(min(fs_value, 1.25 * fs, max(0.03 * hpt, fs)), typography))
        fs_hl = max(fs_value, _size_at_most(min(fs_hl, 1.12 * fs_value), typography)) if not bold else fs_value

    # --- data
    data = CategoryChartData()
    data.categories = cats
    if kind in ("pie", "doughnut"):
        vals = [max(0.0, v or 0.0) for v in values[0]]
        total = sum(vals)
        is_pct = (short_unit(unit) == "%") and 95 <= total <= 105
        keep = amounts and not legend and not is_pct and total > 0
        shares = vals if is_pct or total <= 0 or keep else [round(v / total * 100, 1) for v in vals]
        values = [shares]
        unit = unit if keep else "%"
        data.add_series(series[0].name, shares)
    else:
        for s, vals in zip(series, values):
            data.add_series(s.name, vals)
    all_vals = [v for vs in values for v in vs if v is not None]

    # --- the unit, once
    unit_full = " ".join((unit or "").split())
    glyph = glyph_unit(unit_full)
    head = spec.title or None
    head_is_title = bool(head)
    unit_in_head = False
    if kind not in ("pie", "doughnut") and unit_full and not glyph:
        if head:
            low = head.lower()
            if unit_full.lower() not in low and short_unit(unit_full).lower() not in low:
                head = f"{head.rstrip(' ,.:;')}, {unit_full}"
            unit_in_head = True
        elif _unit_shown_above(slide, bbox, unit_full):
            unit_in_head = True
        else:
            head = unit_full  # a word unit is written once, above the chart: the labels are plain numbers
            unit_in_head = True
    if kind in ("pie", "doughnut") and unit != "%":
        decimals = _decimals(all_vals)  # a pie of the brief's amounts: its slices say the amounts
        fmt_unit = fmt_plain = fmt_emph = label_format(unit, all_vals)
        unit_plain = unit_emph = unit
    elif kind in ("pie", "doughnut"):
        decimals = 0
        fmt_unit = fmt_plain = fmt_emph = label_format("%", [])
        unit_plain = unit_emph = "%"
    else:
        decimals = _decimals(all_vals)
        fmt_unit = label_format(unit, all_vals)
        fmt_plain = fmt_unit if glyph else label_format(None, all_vals)
        fmt_emph = fmt_plain if unit_in_head else fmt_unit
        unit_plain = unit if glyph else None
        unit_emph = unit_plain if unit_in_head else unit

    gf = slide.shapes.add_chart(_TYPE_MAP[kind], Emu(bbox.x), Emu(bbox.y), Emu(bbox.w), Emu(bbox.h), data)
    _OWN_PARTS.add(gf.chart_part)
    chart = gf.chart
    cs = chart._chartSpace
    fix_axis_ids(cs)
    chart.font.size = Pt(fs)
    if family:
        chart.font.name = family
    chart.font.color.rgb = _rgb(text)
    plot = chart.plots[0]
    chart_el = next((c for c in cs.find(f".//{_c('plotArea')}") if _local(c).endswith("Chart")), None)

    # --- title / unit caption: one line at the top left, above the plot
    title_h = 0.0
    chart.has_title = bool(head)
    if head:
        tf = chart.chart_title.text_frame
        tf.text = head
        run = tf.paragraphs[0].runs[0]
        run.font.size = Pt(fs)
        run.font.bold = bool(head_is_title and bold)
        run.font.color.rgb = _rgb(text if head_is_title else muted)
        if family:
            run.font.name = family
        title_el = cs.find(f".//{_c('title')}")
        if title_el is not None:
            _manual_layout(title_el, 0.0, 0.0, None, None, inner=False)
            ov = title_el.find(_c("overlay"))
            if ov is None:
                ov = etree.Element(_c("overlay"))
                _insert_before(title_el, ov, ("spPr", "txPr", "extLst"))
            ov.set("val", "0")
        title_h = fs * 1.5 + 4

    k = _Kit(
        chart=chart, plot=plot, chart_el=chart_el, kind=kind, series=series, values=values, cats=cats, spec=spec,
        palette=palette, accent=accent, ground=ground, text=text, muted=muted, rule=rule,
        fs=fs, fs_value=fs_value, fs_hl=fs_hl, bold=bold, family=family,
        fmt_unit=fmt_unit, fmt_plain=fmt_plain, fmt_emph=fmt_emph, unit=unit, unit_plain=unit_plain, unit_emph=unit_emph,
        decimals=decimals, W=W, H=H, sw=sw, sh=sh, title_h=title_h,
    )
    k.slice_labels = True
    k.capped = capped
    if multi and kind not in ("pie", "doughnut"):
        k.roles = series_roles([s.name for s in series])
    k.styles = _series_styles(k)

    # --- legend: pies always; bars with several series (horizontal bars name their series on the first row
    # instead); lines and areas name each line at its end
    chart.has_legend = False
    k.outside = legend
    if kind in ("pie", "doughnut") and legend:
        _legend(k, cats, side=W / max(H, 1) >= 1.45)
    elif multi and kind == "column":
        _legend(k, [s.name for s in series], side=False)

    if kind in ("column", "bar"):
        _style_bars(k)
    elif kind in ("line", "area"):
        _style_line(k)
    else:
        _style_pie(k)
    _transparent(chart)
    _fonts_everywhere(cs, family)
    # for a caller's own legend: the colour of every slice (series), and for a pie its tint as (base, share over the
    # ground) — a swatch drawn in the base colour at that opacity looks the same and stays a colour of the template
    gf.verstka_colors = list(palette) if kind in ("pie", "doughnut") else [st.get("fill") or st.get("line") or accent for st in k.styles]
    gf.verstka_shades = list(shades) if kind in ("pie", "doughnut") else None
    # a caller trying narrower slots for the chart compares how its labels fit: their width over the slot, and whether
    # they had to be turned or thinned out
    gf.verstka_squeeze = k.squeeze
    gf.verstka_turned = k.turned
    return gf


# ---------------------------------------------------------------------------------------------- axes


def _cat_axis(k: _Kit, fs: float, reverse: bool = False, line: bool = True, skip: int = 1, rotate: bool = False) -> None:
    ca = k.chart.category_axis
    ca.visible = True
    ca.has_major_gridlines = False
    ca.has_minor_gridlines = False
    ca.major_tick_mark = XL_TICK_MARK.NONE
    ca.minor_tick_mark = XL_TICK_MARK.NONE
    ca.tick_label_position = XL_TICK_LABEL_POSITION.LOW
    if line:
        ca.format.line.color.rgb = _rgb(k.rule)
        ca.format.line.width = Pt(0.75)
    else:
        ca.format.line.fill.background()
    _axis_txpr(ca, fs, k.muted, k.family)
    el = ca._element
    if rotate:
        bp = el.find(_c("txPr") + "/" + _a("bodyPr"))
        if bp is not None:
            bp.set("rot", "-2700000")
            bp.attrib.pop("vert", None)
    if reverse:
        scaling = el.find(_c("scaling"))
        orient = scaling.find(_c("orientation")) if scaling is not None else None
        if orient is not None:
            orient.set("val", "maxMin")
    _set_child_val(el, "tickLblSkip", str(max(1, skip)), ("tickMarkSkip", "noMultiLvlLbl", "extLst"))


def _value_axis(k: _Kit, show: bool, fs: float, lo: Optional[float], hi: Optional[float], step: Optional[float] = None) -> None:
    va = k.chart.value_axis
    va.has_minor_gridlines = False
    if lo is not None:
        va.minimum_scale = lo
    if hi is not None:
        va.maximum_scale = hi
    if not show:
        va.has_major_gridlines = False
        va.visible = False
        d = va._element.find(_c("delete"))
        if d is not None:
            d.set("val", "1")  # explicit: some readers take a bare <c:delete/> for «shown»
        return
    va.visible = True
    va.has_major_gridlines = True
    if step:
        va.major_unit = step
    gl = va.major_gridlines.format.line
    gl.color.rgb = _rgb(_mix(k.rule, k.ground, 0.7))
    gl.width = Pt(0.5)
    va.major_tick_mark = XL_TICK_MARK.NONE
    va.minor_tick_mark = XL_TICK_MARK.NONE
    va.format.line.fill.background()
    va.tick_labels.number_format = _tick_format(k.unit, k.decimals)
    va.tick_labels.number_format_is_linked = False
    _axis_txpr(va, fs, k.muted, k.family)


def _nice_floor(v: float) -> float:
    if v <= 0:
        return 0.0
    mag = 10 ** math.floor(math.log10(v))
    return math.floor(v / mag) * mag


def _plot_layout(k: _Kit, left: float, top: float, pw: float, ph: float) -> None:
    pa = k.chart._chartSpace.find(f".//{_c('plotArea')}")
    if pa is not None:
        _manual_layout(pa, left / k.W, top / k.H, pw / k.W, ph / k.H)


# ---------------------------------------------------------------------------------------------- bars


def _style_bars(k: _Kit) -> None:
    horizontal = k.kind == "bar"
    cats, values, series, W, H, fs, family = k.cats, k.values, k.series, k.W, k.H, k.fs, k.family
    n = max(1, len(cats))
    ns = len(series)
    multi = ns > 1
    flat = [v for vs in values for v in vs if v is not None]
    has_neg = any(v < 0 for v in flat)
    hl = k.spec.highlight_index if (k.spec.highlight_index is not None and not multi and 0 <= k.spec.highlight_index < n) else None
    # the one label that carries the unit: the highlight, else the top bar (horizontal) or the tallest column
    emph = hl
    if emph is None and not multi and values[0]:
        vals0 = [(v if v is not None else -math.inf) for v in values[0]]
        emph = 0 if horizontal else max(range(len(vals0)), key=lambda j: (vals0[j], j))
    # horizontal bars with several series name them on the first row («Было: 48») instead of in a legend
    widest_name = max((text_width_pt(s.name, family, fs) for s in series), default=0.0)
    direct = horizontal and multi and ns <= 4 and widest_name <= W * 0.3
    if horizontal and multi and not direct:
        _legend(k, [s.name for s in series], side=False)

    fs_val0 = k.fs_value if (not multi and n <= 8) else fs
    ratio = k.fs_hl / k.fs_value if k.fs_value else 1.0

    def labels(fsv: float) -> list[tuple[str, float, bool]]:
        out = []
        for i, vs in enumerate(values):
            for j, v in enumerate(vs):
                if v is None or v == 0:
                    if horizontal and v == 0:
                        out.append(("0", fsv, False))
                    continue
                if not multi and j == hl:
                    t, size, b = k.emph(v), _snap(fsv * ratio), k.bold
                elif not multi and j == emph:
                    t, size, b = k.emph(v), fsv, False
                else:
                    t, size, b = k.plain(v), fsv, False
                if direct and j == 0:
                    t = f"{series[i].name}{LABEL_SEP}{t}"
                out.append((t, size, b))
        return out

    def lab_w(fsv: float) -> float:
        return max((text_width_pt(t, family, s, b) for t, s, b in labels(fsv)), default=0.0)

    def lab_top(fsv: float) -> float:
        return max((s for _, s, _ in labels(fsv)), default=fsv)

    # category label geometry: horizontal bars carry their labels on the left, wrapped inside 42 % of the frame and
    # stepped down when the wrapped lines would not fit their row
    cat_fs = fs
    cat_w = 0.0
    if horizontal:
        row = max(H - k.title_h - k.legend_h - fs, H * 0.3) / n
        for size in (fs, _snap(fs * 0.9), max(8.0, _snap(fs * 0.82))):
            cat_fs = size
            cat_w = min(max((text_width_pt(c, family, size) for c in cats), default=20.0), W * 0.42)
            lines = max((len(wrap_lines(c, family, size, False, cat_w + 0.5)) for c in cats), default=1)
            if lines * size * 1.2 <= row * 0.92:
                break
    else:
        # single-word labels cannot wrap: one step down when they crowd their column (headroom for a wider font)
        pitch = W / n
        longest = max((max((text_width_pt(w, family, fs) for w in c.split()), default=0.0) for c in cats), default=0.0)
        if longest > pitch * 0.75:
            cat_fs = max(_snap(fs * 0.85), _snap(fs * pitch * 0.75 / max(longest, 1)))

    def box(labels_on: bool, axis_on: bool, fsv: float):
        if horizontal:
            left = cat_w + cat_fs * 0.8
            right = (lab_w(fsv) + fsv * 0.7) if labels_on else fs
            top = k.title_h + (fs * 0.3)
            bottom = k.legend_h + (fs * 1.8 if axis_on else fs * 0.3)
        else:
            pitch0 = W / n
            lines = max((len(wrap_lines(c, family, cat_fs, False, pitch0 * 0.92)) for c in cats), default=1)
            lines = min(lines, 3)
            left = (max(text_width_pt(_fmt_value(v, None, k.decimals) or "0", family, fs) for v in (flat or [0])) + fs * 0.8) if axis_on else 1.0
            right = 1.0
            top = k.title_h + ((lab_top(fsv) * 1.3 + 5) if labels_on else fs * 0.7)
            bottom = k.legend_h + lines * cat_fs * 1.22 + cat_fs * 0.6
        return left, top, max(W - left - right, W * 0.3), max(H - top - bottom, H * 0.3)

    labels_on, axis_on = True, False  # values on the bars replace the value axis
    fs_val = fs_val0
    left, top, pw, ph = box(labels_on, axis_on, fs_val)
    slot = (ph if horizontal else pw) / n
    # bar thickness: gap 60–80 %, but a few bars in a wide frame keep a designed width instead of turning into slabs
    cap = (max(fs_val * 2.6, 0.075 * k.sh / EMU_PER_PT) if horizontal else 0.11 * k.sw / EMU_PER_PT) * (1.0 if not multi else min(ns, 3) * 0.9)
    group = min(slot / 1.7, cap)
    gap = int(max(60, min(300, round((slot / group - 1) * 100))))
    group = slot / (1 + gap / 100)
    bar = group / ns if multi else group
    if not horizontal:
        # every value label must fit over its bar (plus a little of the gap)
        room = bar + (slot - group) * 0.5 if not multi else bar * 1.12
        sizes = (fs_val, _snap(fs * 1.15), fs, _snap(fs * 0.9)) if not multi else (fs, _snap(fs * 0.9), max(8.0, _snap(fs * 0.82)))
        for size in sizes:
            if all(text_width_pt(t, family, s, b) <= room * 0.98 for t, s, b in labels(size)):
                fs_val = size
                break
        else:
            if multi:
                labels_on, axis_on = False, True
            else:
                fs_val = _snap(fs * 0.9)
        left, top, pw, ph = box(labels_on, axis_on, fs_val)
    if horizontal and multi and (ph / n / (1 + gap / 100) / ns) < fs * 0.9:
        labels_on, axis_on = False, True
    if multi and not labels_on and direct:
        direct = False
        _legend(k, [s.name for s in series], side=False)
    left, top, pw, ph = box(labels_on, axis_on, fs_val)

    plot = k.plot
    plot.gap_width = gap
    plot.overlap = -8 if multi else 0
    plot.vary_by_categories = False

    # colours: the story's paint for several series; one series steps back behind its highlight
    muted_fill = muted_tint(k.accent, k.ground)
    for i, ser in enumerate(plot.series):
        ser.invert_if_negative = False
        st = k.styles[i] if multi else {"fill": muted_fill if hl is not None else k.accent}
        if st.get("fill"):
            ser.format.fill.solid()
            ser.format.fill.fore_color.rgb = _rgb(st["fill"])
            ser.format.line.fill.background()
        else:  # a plan: the outline of the bar it aims for
            ser.format.fill.background()
            ser.format.line.color.rgb = _rgb(st.get("line") or k.accent)
            ser.format.line.width = Pt(1.5)
        if not multi and hl is not None:
            pt = ser.points[hl]
            pt.format.fill.solid()
            pt.format.fill.fore_color.rgb = _rgb(k.accent)
            pt.format.line.fill.background()

    # labels
    plot.has_data_labels = labels_on
    if labels_on and k.chart_el is not None:
        pos = "outEnd"
        _set_plot_dlbls(k.chart_el, _dlbls(k.fmt_unit, fs_val, k.text, family, pos))
        for i, ser in enumerate(plot.series):
            st = k.styles[i] if multi else {"label": k.text}
            lab = st.get("label", k.text)
            pts: dict[int, dict] = {}
            for j, v in enumerate(values[i]):
                if v is None:
                    pts[j] = {"delete": True}
                elif v == 0:
                    # a real zero: a column simply has none; a bar row says «0» at the axis instead of looking empty
                    pts[j] = {"fmt": "0", "color": k.muted} if horizontal else {"delete": True}
            if not multi and hl is not None and hl not in pts:
                pts[hl] = k.hl_label(fs_val / k.fs_value if k.fs_value else 1.0)
            elif not multi and emph is not None and emph not in pts:
                pts[emph] = {"fmt": k.fmt_emph}
            if direct and 0 not in pts:
                fill = st.get("fill") or st.get("line") or lab
                pts[0] = {"sername": True, "color": fill if contrast_ratio(fill, k.ground) >= 3.0 else lab}
            _set_ser_dlbls(ser._element, _dlbls(k.fmt_plain, fs_val, lab, family, pos, pts))

    # axes: columns stand on one hairline baseline; horizontal bars start at a common edge and need none (unless < 0)
    _cat_axis(k, cat_fs, reverse=horizontal, line=not horizontal or has_neg)
    lo = hi = step = None
    if flat and not has_neg:
        lo = 0.0
        if labels_on and not axis_on:
            hi = max(flat) or None
    if axis_on and flat:
        lo, hi, step = _nice_scale(min(0.0, min(flat)), max(0.0, max(flat)))
    _value_axis(k, axis_on, fs, lo, hi, step)
    _plot_layout(k, left, top, pw, ph)


# ---------------------------------------------------------------------------------------------- lines & areas


def _seg_in_box(p, q, box) -> float:
    """Length of the segment pq inside the box (x0, y0, x1, y1) — Liang–Barsky clipping."""
    (x0, y0), (x1, y1) = p, q
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, x0 - box[0]), (dx, box[2] - x0), (-dy, y0 - box[1]), (dy, box[3] - y0)):
        if abs(pk) < 1e-12:
            if qk < 0:
                return 0.0
            continue
        t = qk / pk
        if pk < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
    return (t1 - t0) * math.hypot(dx, dy) if t1 > t0 else 0.0


def _box_overlap(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


_CANDIDATES = (("t", 0, 0.0), ("t", -1, 0.35), ("t", 1, 0.35), ("b", 0, 0.6), ("b", -1, 0.8), ("b", 1, 0.8), ("r", 0, 1.0), ("l", 0, 1.0))


def place_point_labels(points, sizes, bounds, gap: float, lines=()) -> list[Optional[tuple[str, float]]]:
    """Where each point's label goes: (dLblPos, horizontal nudge in pt). Above the point is preferred; a label that
    the line would strike (a steady rise or fall runs through a label centred above its point) moves to the free
    side — above-left on a rise, above-right on a fall, below at a dip — keeping clear of every line segment, the
    other labels and markers, and the `bounds` (x0, y0, x1, y1). `points` in pt, y downward; None = no label."""
    segs = []
    for pts in (list(lines) or [points]):
        segs += [(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if pts[i] is not None and pts[i + 1] is not None]
    markers = [p for pts in (list(lines) or [points]) for p in pts if p is not None]
    placed: list[tuple] = []
    out: list[Optional[tuple[str, float]]] = []
    for j, (p, sz) in enumerate(zip(points, sizes)):
        if p is None or sz is None:
            out.append(None)
            continue
        x, y = p
        w, h = sz
        best = None
        for pos, nudge, pref in _CANDIDATES:
            dx = nudge * (w / 2 + gap * 0.6)
            if pos == "t":
                bx = (x + dx - w / 2, y - gap - h, x + dx + w / 2, y - gap)
            elif pos == "b":
                bx = (x + dx - w / 2, y + gap, x + dx + w / 2, y + gap + h)
            elif pos == "r":
                bx = (x + gap, y - h / 2, x + gap + w, y + h / 2)
            else:
                bx = (x - gap - w, y - h / 2, x - gap, y + h / 2)
            pad = (bx[0] - 1.5, bx[1] - 1.5, bx[2] + 1.5, bx[3] + 1.5)
            cost = pref
            cost += 3.0 * sum(_seg_in_box(a, b, pad) for a, b in segs) / max(h, 1.0)
            cost += 4.0 * sum(_box_overlap(pad, o) for o in placed) / max(w * h, 1.0)
            cost += 3.0 * sum(1 for q in markers if q != p and pad[0] <= q[0] <= pad[2] and pad[1] <= q[1] <= pad[3])
            out_of = max(0.0, bounds[0] - bx[0]) + max(0.0, bx[2] - bounds[2]) + max(0.0, bounds[1] - bx[1]) + max(0.0, bx[3] - bounds[3])
            cost += 4.0 * out_of / max(h, 1.0)
            if best is None or cost < best[0] - 1e-9:
                best = (cost, pos, dx, bx)
        placed.append(best[3])
        out.append((best[1], best[2]))
    return out


def _repel(ys: dict, h: float, lo: float, hi: float) -> dict:
    """1-D label repel: move the end labels (centres `ys`) apart until no two are closer than `h`, within [lo, hi]."""
    order = sorted(ys, key=lambda i: ys[i])
    pos = {i: ys[i] for i in order}
    for _ in range(40):
        moved = False
        for a, b in zip(order, order[1:]):
            d = pos[b] - pos[a]
            if d < h:
                push = (h - d) / 2 + 0.01
                pos[a] -= push
                pos[b] += push
                moved = True
        for i in order:
            pos[i] = max(lo + h / 2, min(hi - h / 2, pos[i]))
        if not moved:
            break
    return pos


def _area_overlay(k: _Kit, area_el, colors: list[str]) -> list:
    """The top edge of each area as a 2.25 pt line series over it (a c:lineChart on the same axes): the area itself
    has no outline, so its sides and bottom are not stroked, and the edge carries the end label."""
    sers = area_el.findall(_c("ser"))
    lc = etree.Element(_c("lineChart"))
    etree.SubElement(lc, _c("grouping")).set("val", "standard")
    etree.SubElement(lc, _c("varyColors")).set("val", "0")
    out = []
    n = len(k.cats)
    for i, aser in enumerate(sers):
        ls = etree.SubElement(lc, _c("ser"))
        etree.SubElement(ls, _c("idx")).set("val", str(len(sers) + i))
        etree.SubElement(ls, _c("order")).set("val", str(len(sers) + i))
        tx = aser.find(_c("tx"))
        if tx is not None:
            ls.append(copy.deepcopy(tx))
        color = colors[i % len(colors)]
        ls.append(_sppr(None, line=color, line_w=2.25, no_line=False))
        mk = etree.SubElement(ls, _c("marker"))
        etree.SubElement(mk, _c("symbol")).set("val", "none")
        # the last point: a ringed marker where the end label sits
        dpt = etree.SubElement(ls, _c("dPt"))
        etree.SubElement(dpt, _c("idx")).set("val", str(max(0, n - 1)))
        m2 = etree.SubElement(dpt, _c("marker"))
        etree.SubElement(m2, _c("symbol")).set("val", "circle")
        etree.SubElement(m2, _c("size")).set("val", "7")
        m2.append(_sppr(color, line=k.ground, line_w=1.5, no_line=False))
        etree.SubElement(dpt, _c("bubble3D")).set("val", "0")
        for tag in ("cat", "val"):
            el = aser.find(_c(tag))
            if el is not None:
                ls.append(copy.deepcopy(el))
        etree.SubElement(ls, _c("smooth")).set("val", "0")
        out.append(ls)
    etree.SubElement(lc, _c("marker")).set("val", "1")
    for ax in area_el.findall(_c("axId")):
        lc.append(copy.deepcopy(ax))
    area_el.addnext(lc)
    return out


def _set_categories(k: _Kit, cats: list[str]) -> None:
    """The chart's categories rewritten (its data sheet too): the shortened labels of a crowded time axis."""
    data = CategoryChartData()
    data.categories = cats
    for ser, vals in zip(k.series, k.values):
        data.add_series(ser.name, vals)
    try:
        k.chart.replace_data(data)
    except Exception:  # noqa: BLE001
        pass


def _style_line(k: _Kit) -> None:
    """One series (≤ 8 points): every point labelled off the line, the highlight (or the last point) in the accent on a
    larger marker, no value axis. Several series or many points: a quiet value axis on round ticks and each line named
    once at its end, in its own colour, the end labels kept apart. An area: a soft fill under a 2.25 pt edge."""
    cats, values, series, W, H, fs, family = k.cats, k.values, k.series, k.W, k.H, k.fs, k.family
    kind = k.kind
    n = max(1, len(cats))
    ns = len(series)
    multi = ns > 1
    flat = [v for vs in values for v in vs if v is not None]
    has_neg = any(v < 0 for v in flat)
    hl = None
    if not multi and kind == "line":
        hl = k.spec.highlight_index if (k.spec.highlight_index is not None and 0 <= k.spec.highlight_index < n) else n - 1
    slot = W / n
    fs_val = k.fs_value if (not multi and n <= 6) else fs
    ratio = k.fs_hl / k.fs_value if k.fs_value else 1.0

    def point_text(i: int, j: int) -> str:
        v = values[i][j]
        return k.emph(v) if j == hl else k.plain(v)

    def widest(size: float) -> float:
        return max((text_width_pt(point_text(0, j), family, _snap(size * ratio) if j == hl else size, k.bold and j == hl) for j in range(n) if values[0][j] not in (None, 0)), default=0.0)

    # a label on every point while they stay few and apart; an area reads as a mass (one end label, a quiet axis)
    every_point = not multi and kind == "line" and n <= 8
    if every_point and widest(fs_val) > slot * 0.95:
        fs_val = fs
        if widest(fs_val) > slot * 1.05:
            every_point = False
    axis_on = multi or not every_point
    ends = not every_point
    # end labels name their line when there are several (no legend); a long series name falls back to a legend
    names = [s.name for s in series]
    named = multi and max((text_width_pt(nm, family, fs) for nm in names), default=0.0) <= W * 0.22
    if multi and not named:
        _legend(k, names, side=False)

    def end_text(i: int) -> str:
        last = values[i][-1] if values[i] else None
        t = k.emph(last) if not multi else k.plain(last)
        return f"{names[i]}{LABEL_SEP}{t}" if named else t

    # one line: its end label is the chart's emphasis (accent, a size up where the template does not use bold)
    end_size = fs_val if multi else _snap(fs_val * ratio)
    end_w = max((text_width_pt(end_text(i), family, end_size, k.bold) for i in range(ns)), default=0.0) if ends else 0.0

    # category labels stay at the chart's text size (never under the deck's small size) on one line each: measured
    # against the real slot — the plot's width over the points, the value axis and the end label take their share of
    # the frame — a time axis too narrow for its words shortens them («1-й месяц» → «1-й мес.»), and still too
    # wide, every k-th label is shown (a line is continuous)
    cat_fs = fs

    # value range
    lo = hi = step = None
    if flat:
        mn, mx = min(flat), max(flat)
        if axis_on:
            if has_neg:
                lo_raw = mn
            elif kind == "area" or mn <= 0.45 * mx:
                lo_raw = 0.0
            else:
                lo_raw = max(0.0, mn - (mx - mn) * 0.2)
            lo, hi, step = _nice_scale(lo_raw, max(mx, 0.0))
            if not has_neg:
                lo = max(0.0, lo)
        else:
            # no axis, so no false zero: the lowest point sits a fifth of the height above the category labels
            lo = 0.0 if (mn >= 0 and mn <= 0.45 * mx) else (mn - (mx - mn) * 0.25)
            if mn >= 0:
                lo = max(0.0, lo)
            hi = mx if mx > lo else None

    marker = 7 if multi else 8
    lab_h = fs_val * 1.2
    top = k.title_h + ((max(fs_val, _snap(fs_val * ratio)) * 1.25 + marker / 2 + 6) if every_point else (fs * 0.9 if ends else fs * 0.9))
    bottom = k.legend_h + cat_fs * 1.25 + cat_fs * 0.6
    if axis_on:
        tick_w = max((text_width_pt(_fmt_value(v, None, k.decimals) or "0", family, cat_fs) for v in ([lo or 0.0, hi or 0.0] + flat)), default=10.0)
        left = tick_w + fs * 1.2
    else:
        left = max(1.0, widest(fs_val) / 2 - slot / 2 + 4)
    right = max(1.0, end_w + fs * 0.9 - slot / 2 + 6) if ends else max(1.0, widest(fs_val) / 2 - slot / 2 + 4)
    pw, ph = max(W - left - right, W * 0.3), max(H - top - bottom, H * 0.3)
    real_slot = pw / n
    # a label wider than its slot is broken by the renderer, even inside a word; the capped mode measures the slot
    # strictly (LibreOffice ignores tickLblSkip and stacks a long label letter by letter)
    room = real_slot * (0.75 if k.capped else 0.92)
    longest = max((text_width_pt(c, family, cat_fs) for c in cats), default=0.0)
    if longest > room:
        short = short_categories(cats, joiner=not k.capped)
        if short != cats:
            cats = k.cats = short
            _set_categories(k, short)
            longest = max((text_width_pt(c, family, cat_fs) for c in cats), default=0.0)
    skip = max(1, math.ceil(longest / room)) if longest > room else 1
    k.squeeze = longest / max(real_slot, 1.0)
    short_before = list(cats)
    rotate = False
    # a label past its slot is broken by LibreOffice inside the word («Сейч ас»), whatever tickLblSkip says: the
    # capped mode measures the slot strictly; the others turn or thin their labels once one runs 10 % past its slot
    if (k.capped and longest > room) or (not k.capped and longest > 1.1 * real_slot):
        if n >= 5:
            # still too wide: the labels turn by 45° (their height takes the room under the plot)
            rotate = True
            skip = 1
            bottom += max(0.0, longest * 0.71 + cat_fs * 0.71 - cat_fs * 1.25)
            ph = max(H - top - bottom, H * 0.3)
        else:
            # a few long labels: every k-th label is kept, the others are blank in the chart's data (the readers
            # that ignore tickLblSkip would stack them letter by letter)
            keep = max(1, math.ceil(longest / room))
            blank = [c if (j % keep == 0 or j == n - 1) else "" for j, c in enumerate(cats)]
            if blank != cats:
                cats = k.cats = blank
                _set_categories(k, blank)
            skip = 1
    k.turned = rotate or cats != short_before  # turned or thinned out: every label shown is whole
    if skip > 1 and n > 2:
        # the labels shown are the first, the last and every k-th between: pick k so that the last one falls on it
        skip = next((kk for kk in range(skip, n) if (n - 1) % kk == 0), skip)

    # paint
    area_lines = []
    colors = []
    for i, ser in enumerate(k.plot.series):
        st = k.styles[i]
        color = st.get("fill") or st.get("line") or k.accent
        dashed = st.get("role") == "plan"
        if dashed and k.roles:
            color = k.muted
        colors.append(color)
        ser.smooth = False
        if kind == "line":
            ln = ser.format.line
            ln.color.rgb = _rgb(color)
            ln.width = Pt(1.5 if dashed else 2.25)
            if dashed:
                ln.dash_style = MSO_LINE_DASH_STYLE.DASH
                ser.marker.style = XL_MARKER_STYLE.NONE
            else:
                ser.marker.style = XL_MARKER_STYLE.CIRCLE
                ser.marker.size = marker
                ser.marker.format.fill.solid()
                ser.marker.format.fill.fore_color.rgb = _rgb(color)
                ser.marker.format.line.color.rgb = _rgb(k.ground)
                ser.marker.format.line.width = Pt(1.5)
        else:
            sp = _sppr(color, 0.28 if not _is_dark(k.ground) else 0.38)
            _replace(ser._element, "spPr", sp, ("invertIfNegative", "pictureOptions", "marker", "dPt", "dLbls", "trendline", "errBars", "cat", "val", "smooth", "extLst"))
    if hl is not None:
        mk = k.plot.series[0].points[hl].marker
        mk.style = XL_MARKER_STYLE.CIRCLE
        mk.size = 11
        mk.format.fill.solid()
        mk.format.fill.fore_color.rgb = _rgb(k.accent)
        mk.format.line.color.rgb = _rgb(k.ground)
        mk.format.line.width = Pt(2)
    if kind == "area" and k.chart_el is not None:
        area_lines = _area_overlay(k, k.chart_el, colors)
        k.plot.has_data_labels = False

    # geometry of the points in the chart frame (pt, y down): points sit in the middle of their category slots
    span = ((hi if hi is not None else (max(flat) if flat else 1.0)) - (lo if lo is not None else (min(flat) if flat else 0.0))) or 1.0
    base_lo = lo if lo is not None else (min(flat) if flat else 0.0)

    def xy(j: int, v: Optional[float]):
        if v is None:
            return None
        return left + (j + 0.5) * pw / n, top + ph * (1 - (v - base_lo) / span)

    lines_xy = [[xy(j, v) for j, v in enumerate(vs)] for vs in values]
    gap = marker / 2 + 3

    if k.chart_el is not None:
        if every_point:
            k.plot.has_data_labels = True
            sizes = []
            for j in range(n):
                v = values[0][j]
                if v in (None, 0):
                    sizes.append(None)
                    continue
                size = _snap(fs_val * ratio) if j == hl else fs_val
                sizes.append((text_width_pt(point_text(0, j), family, size, k.bold and j == hl) * 1.08 + 2, size * 1.2))
            bounds = (0.0, k.title_h, W, H - bottom + cat_fs * 0.4)
            placed = place_point_labels(lines_xy[0], sizes, bounds, gap)
            _set_plot_dlbls(k.chart_el, _dlbls(k.fmt_unit, fs_val, k.text, family, "t"))
            pts: dict[int, dict] = {}
            for j, v in enumerate(values[0]):
                if v in (None, 0) or placed[j] is None:
                    pts[j] = {"delete": True}
                    continue
                pos, dx = placed[j]
                o = k.hl_label(fs_val / k.fs_value if k.fs_value else 1.0) if j == hl else {}
                o = {**o, "pos": pos}
                if dx:
                    o["dx"] = dx / W
                pts[j] = o
            _set_ser_dlbls(k.plot.series[0]._element, _dlbls(k.fmt_plain, fs_val, k.text, family, "t", pts))
        else:
            if kind == "line":
                k.plot.has_data_labels = True
                _set_plot_dlbls(k.chart_el, _dlbls(k.fmt_unit, fs_val, k.text, family, "r"))
            targets = area_lines if kind == "area" else [s._element for s in k.plot.series]
            # end labels right of the last point, pushed apart vertically where two lines end close together
            ends_y = {i: lines_xy[i][-1][1] for i in range(ns) if lines_xy[i] and lines_xy[i][-1] is not None and values[i][-1] not in (None, 0)}
            moved = _repel(ends_y, lab_h * 1.05, k.title_h, H - bottom) if ends_y else {}
            for i, ser_el in enumerate(targets):
                st = k.styles[i]
                color = colors[i]
                lab_color = color if contrast_ratio(color, k.ground) >= 3.0 else (k.text if st.get("role") != "past" else k.muted)
                pts = {}
                if i in ends_y:
                    o = {"color": lab_color, "bold": k.bold, "pos": "r", "fmt": k.fmt_emph if not multi else k.fmt_plain, "size": end_size}
                    if named:
                        o["sername"] = True
                    dy = moved[i] - ends_y[i]
                    if abs(dy) > 0.5:
                        o["dy"] = dy / H
                    pts[n - 1] = o
                if hl is not None and hl != n - 1 and values[i][hl] not in (None, 0):
                    p = lines_xy[i][hl]
                    size = _snap(fs_val * ratio)
                    w = text_width_pt(k.emph(values[i][hl]), family, size, k.bold) * 1.08 + 2
                    (pos, dx), = place_point_labels([p], [(w, size * 1.2)], (0.0, k.title_h, W, H - bottom), gap, lines=[lines_xy[i]])
                    o = {**k.hl_label(fs_val / k.fs_value if k.fs_value else 1.0), "pos": pos}
                    if dx:
                        o["dx"] = dx / W
                    pts[hl] = o
                _set_ser_dlbls(ser_el, _dlbls(k.fmt_plain, fs_val, lab_color, family, None, pts, show_val=False))

    # the baseline implies zero: without a value axis over a raised minimum there is none
    _cat_axis(k, cat_fs, skip=skip, line=axis_on or not (lo and lo > 0), rotate=rotate)
    _value_axis(k, axis_on, cat_fs, lo, hi, step)
    ax = k.chart.category_axis._element
    _set_child_val(ax, "lblOffset", "100", ("tickLblSkip", "tickMarkSkip", "noMultiLvlLbl", "extLst"))
    va = k.chart.value_axis._element
    _set_child_val(va, "crossBetween", "between", ("majorUnit", "minorUnit", "dispUnits", "extLst"))
    _plot_layout(k, left, top, pw, ph)


# ---------------------------------------------------------------------------------------------- pies


def _style_pie(k: _Kit) -> None:
    shares, cats, W, H, fs, family = k.values[0], k.cats, k.W, k.H, k.fs, k.family
    n = max(1, len(cats))
    ser = k.plot.series[0]
    total = sum(v for v in shares if v) or 1.0
    ring = k.kind == "doughnut"
    palette = k.palette
    for j in range(n):
        pt = ser.points[j]
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = _rgb(palette[j % len(palette)])
        pt.format.line.color.rgb = _rgb(k.ground)
        pt.format.line.width = Pt(1.5 if not ring else 2.0)
    fine = label_format("%", [0.5])  # one decimal, for a slice under 1 % only

    amounts = (k.unit or "%") != "%"

    def label(v: float) -> str:
        return _fmt_value(v, k.unit, k.decimals) if amounts else _fmt_value(v, "%", 1 if v < 1 else 0)

    def geometry(outside: bool):
        m = fs * (2.6 if outside else 0.6)
        avail_w = W - k.legend_w - 2 * m
        avail_h = H - k.title_h - k.legend_h - 2 * m
        side = max(min(avail_w, avail_h), min(W, H) * 0.3)
        return m, avail_h, side

    # which labels fit inside their slice: the label against the chord of the slice where it sits (with headroom for
    # a substituted, wider font); a pie puts the others outside, a doughnut leaves them to the legend
    def decide(side: float, size: float) -> dict[int, str]:
        r = side / 2
        out: dict[int, str] = {}
        for j, v in enumerate(shares):
            if not v:
                continue
            s = v / total
            w = text_width_pt(label(v), family, size, k.bold) * 1.15 + 6
            h = size * 1.2 + 2
            chord = lambda rho: 2 * rho * math.sin(min(math.pi * s, math.pi / 2)) if s < 0.5 else 2 * rho  # noqa: E731
            # the wedge narrows toward the centre: the chord is taken at the label's inner edge
            if ring:
                rho = r * (1 + HOLE_SIZE / 100) / 2
                out[j] = "in" if (chord(rho - h / 2) >= w and r * (1 - HOLE_SIZE / 100) * 0.8 >= h) else "none"
            elif s >= 0.25 and chord(r * 0.5 - h / 2) >= w:
                out[j] = "ctr"
            elif chord(max(r - max(w, h) / 2 - 4, r * 0.4) - h / 2) >= w:
                out[j] = "inEnd"
            else:
                out[j] = "outEnd" if k.outside else "none"
        return out

    size = k.fs_value
    m, avail_h, side = geometry(False)
    if k.capped:
        size = max(min(size, _snap(side / 8.0)), min(fs, 8.0))  # a slice label never larger than an eighth of the pie
    where = decide(side, size)
    if any(v in ("outEnd", "none") for v in where.values()) and size > fs:
        smaller = decide(side, fs)
        # a step down when it brings a label inside (without a legend of its own, a thin slice stays unlabelled
        # whatever the size: the rest keep the larger type)
        if k.outside or sum(v not in ("outEnd", "none") for v in smaller.values()) > sum(v not in ("outEnd", "none") for v in where.values()):
            size, where = fs, smaller
    outside = any(v == "outEnd" for v in where.values())
    if outside:
        m, avail_h, side = geometry(True)
        where = decide(side, size)

    pts: dict[int, dict] = {}
    for j, v in enumerate(shares):
        if not v or where.get(j) == "none" or not k.slice_labels:
            pts[j] = {"delete": True}
            continue
        fill = palette[j % len(palette)]
        if where[j] == "outEnd":
            pts[j] = {"color": k.text, "pos": "outEnd"}
        else:
            pts[j] = {"color": _label_on(fill, k.text, k.ground)}
            if not ring:
                pts[j]["pos"] = where[j]
        if v < 1 and not amounts:
            pts[j]["fmt"] = fine
    pos = None if ring else "ctr"
    k.plot.has_data_labels = k.slice_labels
    if k.chart_el is not None:
        if k.slice_labels:
            _set_plot_dlbls(k.chart_el, _dlbls(k.fmt_unit, size, k.text, family, pos, leader_lines=False, bold=k.bold))
            _set_ser_dlbls(ser._element, _dlbls(k.fmt_unit, size, k.text, family, pos, pts, leader_lines=False, bold=k.bold))
        for tag, val in (("firstSliceAng", "0"), ("holeSize", str(HOLE_SIZE))):
            el = k.chart_el.find(_c(tag))
            if el is not None:
                el.set("val", val)
            elif tag == "firstSliceAng":
                _set_child_val(k.chart_el, tag, val, ("holeSize", "extLst"))
    # the circle and its legend as one group: left-aligned in a column, centred when the chart has the slide to itself
    group = side + (fs * 2.0 + k.legend_w if k.legend_w else 0.0)
    x = (W - group) / 2 if (not k.legend_w or W > 0.7 * k.sw / EMU_PER_PT) else m
    y = k.title_h + m + max(0.0, (avail_h - side) / 2)
    _plot_layout(k, x, y, side, side)
    if k.legend_w and k.chart.has_legend:
        lg = k.chart._chartSpace.find(f".//{_c('legend')}")
        if lg is not None:
            lx = (x + side + fs * 2.0) / W
            _manual_layout(lg, lx, 0.5 - min(0.45, (n * fs * 1.5) / H / 2), min(1.0 - lx, k.legend_w / W + 0.02), min(0.9, (n * fs * 1.5 + fs) / H), inner=False)


# ---------------------------------------------------------------------------------------------- geometry for callers


def chart_plot_bbox(graphic_frame) -> Optional[Bbox]:
    """The plot area of a chart made here, in slide EMU (from its manual layout) — e.g. to align a caption with it."""
    try:
        cs = graphic_frame.chart._chartSpace
        ml = cs.find(f".//{_c('plotArea')}/{_c('layout')}/{_c('manualLayout')}")
        vals = {_local(e): float(e.get("val")) for e in ml if e.get("val") not in (None, "inner", "outer", "edge", "factor")}
        gx, gy, gw, gh = graphic_frame.left, graphic_frame.top, graphic_frame.width, graphic_frame.height
        return Bbox(x=int(gx + vals["x"] * gw), y=int(gy + vals["y"] * gh), w=int(vals["w"] * gw), h=int(vals["h"] * gh))
    except Exception:  # noqa: BLE001
        return None


def doughnut_hole_bbox(graphic_frame) -> Optional[Bbox]:
    """The square inscribed in a doughnut's hole, in slide EMU: where a composer can set the total or the lead share
    as a native text box."""
    pb = chart_plot_bbox(graphic_frame)
    if pb is None:
        return None
    d = min(pb.w, pb.h)
    inner = d * HOLE_SIZE / 100 / math.sqrt(2)
    cx, cy = pb.x + pb.w / 2, pb.y + pb.h / 2
    return Bbox(x=int(cx - inner / 2), y=int(cy - inner / 2), w=int(inner), h=int(inner))
