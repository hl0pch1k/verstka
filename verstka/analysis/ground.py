"""What a slide really stands on: the painted layers of master, layout and slide, and the ground under a box.

The slide's own shapes are only the top of the picture. A layout or a master may paint a full-bleed picture (a blue
gradient behind a white cover title), a coloured panel under the body, a band under the heading. Reading only the
slide's shapes and the `p:bg` chain, the analysis took such slides for white ones (white-on-white 1.0:1 contrast on a
blue cover). `painted_layers` lists everything that paints, in z-order; `ground_at` answers «what colour is under this
box»; `slide_ground` is the ground of the whole slide (family, colour, kind) used by `shapes.slide_family`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

from lxml import etree

from verstka.analysis.xmlns import find, local_name, q
from verstka.ingest.package import PptxPackage
from verstka.schemas.common import Bbox, Family, ShapeKind, contrast_ratio, hex_to_rgb, relative_luminance, rgb_to_hex

_FULL_BLEED = 0.85  # share of the slide a shape must cover to be the slide's ground
_OPAQUE = 0.85  # share of a picture's pixels that must be opaque for it to hide what lies under it
_BUSY_STD = 40.0  # luminance stdev (0–255) above which a picture is a photo, not a calm ground
_SAME_GROUND = 1.2  # a layer picture this close (contrast ratio) to the p:bg colour only textures the same ground (VK Tech: ≤ 1.16)


@dataclass
class PaintedLayer:
    """One painted element under the slide's text, with the colour it paints."""

    box: Bbox
    hex: Optional[str]
    kind: str  # solid | gradient | pattern | image
    source: str  # master | layout | slide
    z: int  # global z-order: master < layout < slide
    placeholder: bool = False
    has_text: bool = False
    opaque: bool = True  # hides what lies under it (fill alpha ≥ 0.5, picture ≥ 85 % opaque pixels)
    busy: bool = False  # a photo (luminance stdev > 40): colour decisions on it are uncertain
    shape_id: Optional[str] = None
    alpha: float = 1.0  # opacity of a solid fill (a semi-opaque veil is blended with what lies under it)
    custom_geom: bool = False  # a freeform: its box is not what it paints (rays, curves, blots) — never a ground


@dataclass
class GroundInfo:
    family: Family
    hex: Optional[str]
    kind: Optional[str]  # solid | gradient | pattern | image | render | None
    uncertain: bool = False
    source: str = "bg"  # layer:<master|layout|slide> | panel | bg | render | text | default
    cover: float = 1.0  # share of the slide the ground's layer covers (a panel leaves the p:bg visible as a frame)
    bg_hex: Optional[str] = None  # the p:bg chain's colour (what shows around a panel)


# ---------------------------------------------------------------------------- colour helpers


def _blend(a: str, b: str, t: float) -> str:
    ra, ga, ba = hex_to_rgb(a)
    rb, gb, bb = hex_to_rgb(b)
    return rgb_to_hex(ra * (1 - t) + rb * t, ga * (1 - t) + gb * t, ba * (1 - t) + bb * t)


_PATTERN_DENSITY = {
    "pct5": 0.05, "pct10": 0.1, "pct20": 0.2, "pct25": 0.25, "pct30": 0.3, "pct40": 0.4, "pct50": 0.5, "pct60": 0.6,
    "pct70": 0.7, "pct75": 0.75, "pct80": 0.8, "pct90": 0.9, "ltHorz": 0.25, "ltVert": 0.25, "dkHorz": 0.5, "dkVert": 0.5,
    "narHorz": 0.33, "narVert": 0.33, "ltDnDiag": 0.25, "ltUpDiag": 0.25, "dkDnDiag": 0.5, "dkUpDiag": 0.5,
}


def pattern_fill_hex(resolver, patt: etree._Element) -> Optional[str]:
    """The colour a pattern fill reads as from a distance: foreground and background blended by the pattern's ink
    density (50 % for patterns without a known density)."""
    fg_el = find(patt, "a:fgClr")
    bg_el = find(patt, "a:bgClr")
    fg = resolver.resolve_color(fg_el[0]) if fg_el is not None and len(fg_el) else None
    bg = resolver.resolve_color(bg_el[0]) if bg_el is not None and len(bg_el) else None
    if fg and bg:
        return _blend(bg, fg, _PATTERN_DENSITY.get(patt.get("prst") or "", 0.5))
    return fg or bg


def gradient_mean_hex(resolver, grad: etree._Element) -> Optional[str]:
    """The mean colour of a gradient (stops weighted by the span each one covers)."""
    stops = []
    for gs in grad.findall(q("a:gsLst") + "/" + q("a:gs")):
        if not len(gs):
            continue
        hx = resolver.resolve_color(gs[0])
        if hx:
            try:
                pos = int(gs.get("pos") or 0) / 100000.0
            except ValueError:
                pos = 0.0
            stops.append((pos, hx))
    if not stops:
        return None
    stops.sort()
    if len(stops) == 1:
        return stops[0][1]
    acc = [0.0, 0.0, 0.0]
    total = 0.0
    for (p0, h0), (p1, h1) in zip(stops, stops[1:]):
        w = max(p1 - p0, 0.0)
        r0, g0, b0 = hex_to_rgb(h0)
        r1, g1, b1 = hex_to_rgb(h1)
        acc[0] += w * (r0 + r1) / 2
        acc[1] += w * (g0 + g1) / 2
        acc[2] += w * (b0 + b1) / 2
        total += w
    # the ends beyond the first and last stop are painted in those stops' colours
    for w, h in ((stops[0][0], stops[0][1]), (1.0 - stops[-1][0], stops[-1][1])):
        if w > 0:
            r, g, b = hex_to_rgb(h)
            acc[0] += w * r
            acc[1] += w * g
            acc[2] += w * b
            total += w
    if total <= 0:
        return stops[0][1]
    return rgb_to_hex(acc[0] / total, acc[1] / total, acc[2] / total)


def package_key(package: PptxPackage) -> tuple:
    """A cache key for one version of one file (an id() may be reused by the next package opened)."""
    try:
        st = package.path.stat()
        return (str(package.path), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(package.path), id(package))


_PIC_CACHE: dict[tuple, Optional[tuple[str, float, float]]] = {}


def picture_stats(package: PptxPackage, image_part: Optional[str]) -> Optional[tuple[str, float, float]]:
    """(median colour of the opaque pixels, opaque share, luminance stdev) of an embedded raster picture; None for
    vector or unreadable pictures. Cached per package and part."""
    if not image_part or not package.exists(image_part) or image_part.lower().endswith((".svg", ".emf", ".wmf")):
        return None
    key = (package_key(package), image_part)
    if len(_PIC_CACHE) > 2048:
        _PIC_CACHE.clear()  # a long-running server audits many decks: keep the cache bounded
    if key not in _PIC_CACHE:
        try:
            import numpy as np
            from PIL import Image

            with Image.open(BytesIO(package.read(image_part))) as im:
                a = np.asarray(im.convert("RGBA").resize((64, 36)), dtype=np.float32)
            op = a[..., 3] > 200
            share = float(op.mean())
            if op.any():
                px = a[..., :3][op]
                med = np.median(px, axis=0)
                lum = 0.299 * px[:, 0] + 0.587 * px[:, 1] + 0.114 * px[:, 2]
                _PIC_CACHE[key] = (rgb_to_hex(*med), share, float(lum.std()))
            else:
                _PIC_CACHE[key] = (None, 0.0, 0.0)  # type: ignore[assignment]
        except Exception:  # noqa: BLE001
            _PIC_CACHE[key] = None
    return _PIC_CACHE[key]


# ---------------------------------------------------------------------------- layers


def _blip_part(package: PptxPackage, part: str, el: etree._Element) -> Optional[str]:
    """The raster picture of a p:pic or of a shape filled with a picture (the PNG fallback of an SVG blip)."""
    blip = el.find(".//" + q("a:blip"))
    if blip is None:
        return None
    rid = blip.get(q("r:embed"))
    return package.target_of(part, rid) if rid else None


def _shape_paint(package: PptxPackage, part: str, el: etree._Element, resolver) -> Optional[tuple[Optional[str], str, bool, bool, float]]:
    """(hex, kind, opaque, busy, alpha) of what a shape paints, or None when it paints nothing."""
    tag = local_name(el)
    if tag == "pic":
        stats = picture_stats(package, _blip_part(package, part, el))
        if stats is None:
            return None
        med, share, std = stats
        return med, "image", share >= _OPAQUE and med is not None, std > _BUSY_STD, 1.0
    if tag != "sp":
        return None
    spPr = find(el, "p:spPr")
    if spPr is None:
        return None
    if find(spPr, "a:noFill") is not None:
        return None
    sf = find(spPr, "a:solidFill")
    if sf is not None and len(sf):
        hx = resolver.resolve_color(sf[0])
        al = sf[0].find(q("a:alpha"))
        try:
            alpha = max(0.0, min(1.0, int(al.get("val") or 100000) / 100000.0)) if al is not None else 1.0
        except ValueError:
            alpha = 1.0
        return (hx, "solid", alpha >= 0.5, False, alpha) if hx else None
    gf = find(spPr, "a:gradFill")
    if gf is not None:
        hx = gradient_mean_hex(resolver, gf)
        # a gradient fading to transparent (a vignette, rays) does not hide what lies under it
        faded = any(_int(a.get("val"), 100000) < 50000 for a in gf.iter(q("a:alpha")))
        return (hx, "gradient", not faded, False, 1.0) if hx else None
    pf = find(spPr, "a:pattFill")
    if pf is not None:
        hx = pattern_fill_hex(resolver, pf)
        return (hx, "pattern", True, False, 1.0) if hx else None
    if find(spPr, "a:blipFill") is not None:
        stats = picture_stats(package, _blip_part(package, part, spPr))
        if stats is None:
            return None
        med, share, std = stats
        return med, "image", share >= _OPAQUE and med is not None, std > _BUSY_STD, 1.0
    ref = find(el, "p:style/a:fillRef")
    if ref is not None and len(ref):
        try:
            idx = int(ref.get("idx") or 0)
        except ValueError:
            idx = 0
        if idx > 0:
            hx = resolver.resolve_color(ref[0])
            return (hx, "solid", True, False, 1.0) if hx else None
    return None


def _int(v: Optional[str], default: int) -> int:
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default


def _shows_master(root: Optional[etree._Element]) -> bool:
    return root is None or root.get("showMasterSp") not in ("0", "false")


_LAYER_CACHE: dict[tuple, list[PaintedLayer]] = {}


def _part_layers(package: PptxPackage, part: str, ctx, source: str, z0: int) -> list[PaintedLayer]:
    """Painted shapes of one part (master, layout or slide) in z-order, with slide coordinates."""
    from verstka.analysis.shapes import extract_shapes

    key = (package_key(package), part, ctx.master_part or "")
    if source != "slide" and key in _LAYER_CACHE:
        return [copy.copy(layer) for layer in _LAYER_CACHE[key]]
    pctx = copy.copy(ctx)
    pctx.slide_part = part  # picture relationships resolve against the part that holds them
    out: list[PaintedLayer] = []
    slide_w, slide_h = package.slide_size
    for s in extract_shapes(package, part, pctx):
        if s.element is None or s.bbox.w <= 0 or s.bbox.h <= 0:
            continue
        if source != "slide" and s.is_placeholder:
            continue  # a layout's placeholders are only prompts: the slide draws its own
        if s.kind == ShapeKind.pic and s.bbox.area < 0.003 * slide_w * slide_h:
            continue  # an icon: never a ground, not worth decoding
        paint = _shape_paint(package, part, s.element, ctx.resolver)
        if paint is None:
            continue
        hx, kind, opaque, busy, alpha = paint
        out.append(PaintedLayer(box=s.bbox, hex=hx, kind=kind, source=source, z=z0 + s.z, placeholder=s.is_placeholder, has_text=s.has_text, opaque=opaque, busy=busy, shape_id=s.id, alpha=alpha, custom_geom=s.geometry == "custom"))
    if source != "slide":
        if len(_LAYER_CACHE) > 512:
            _LAYER_CACHE.clear()
        _LAYER_CACHE[key] = [copy.copy(layer) for layer in out]
    return out


def painted_layers(package: PptxPackage, slide_part: str, ctx) -> list[PaintedLayer]:
    """Everything that paints on a slide, bottom to top: the master's shapes (unless the layout or the slide hides
    them), the layout's non-placeholder shapes, then the slide's own shapes."""
    slide_root = package.xml(slide_part)
    layers: list[PaintedLayer] = []
    show_layout = _shows_master(slide_root)
    if show_layout and ctx.master_part and _shows_master(ctx.layout):
        layers += _part_layers(package, ctx.master_part, ctx, "master", 0)
    if show_layout and ctx.layout_part:
        layers += _part_layers(package, ctx.layout_part, ctx, "layout", 100000)
    layers += _part_layers(package, slide_part, ctx, "slide", 200000)
    layers.sort(key=lambda layer: layer.z)
    return layers


def _bg_chain(package: PptxPackage, slide_part: str, ctx) -> tuple[Optional[str], Optional[str]]:
    """(hex, kind) of the first p:bg of slide → layout → master; a picture ground gives its median colour."""
    from verstka.analysis.shapes import _bg_hex, background_picture_color

    for root in (package.xml(slide_part), ctx.layout, ctx.master):
        if root is None:
            continue
        hx, kind = _bg_hex(root, ctx.resolver)
        if kind:
            if kind == "image":
                return background_picture_color(package, slide_part, ctx), "image"
            return hx, kind
    return None, None


def ground_at(package: PptxPackage, slide_part: str, ctx, bbox: Bbox, layers: Optional[list[PaintedLayer]] = None) -> tuple[Optional[str], Optional[str], bool]:
    """(hex, kind, uncertain) of the ground under `bbox`: the topmost opaque painted layer covering ≥ 60 % of the box
    (the box's own shape excluded; a filled text shape — a pill, a card — is a ground for what stands inside it),
    else the p:bg chain. `uncertain` for pictures that are photos and for gradients (their colour varies under the
    box)."""
    layers = painted_layers(package, slide_part, ctx) if layers is None else layers
    area = max(bbox.area, 1)
    for layer in sorted(layers, key=lambda la: -la.z):
        if not layer.opaque or layer.hex is None:
            continue
        if layer.box.x == bbox.x and layer.box.y == bbox.y and layer.box.w == bbox.w and layer.box.h == bbox.h:
            continue  # the element itself
        if layer.box.intersection(bbox) >= 0.6 * area:
            return layer.hex, layer.kind, layer.busy or layer.kind == "gradient"
    hx, kind = _bg_chain(package, slide_part, ctx)
    return hx, kind, kind == "image"


def _family_of(hex_: str) -> Family:
    return Family.dark if relative_luminance(hex_) < 0.3 else Family.light


def _body_region(shapes, slide_w: int, slide_h: int) -> Bbox:
    """Where the slide's text stands (the union of its text shapes of some size), or the middle of the slide."""
    boxes = [s.bbox for s in shapes if s.has_text and s.bbox.area >= 0.01 * slide_w * slide_h]
    if not boxes:
        return Bbox(x=int(0.2 * slide_w), y=int(0.3 * slide_h), w=int(0.6 * slide_w), h=int(0.5 * slide_h))
    u = boxes[0]
    for b in boxes[1:]:
        u = u.union(b)
    return u


def slide_ground(package: PptxPackage, slide_part: str, ctx, shapes, image_path: Optional[str] = None) -> GroundInfo:
    """The ground of a whole slide.

    1. The topmost opaque element that is either full-bleed (≥ 85 % of the slide, any layer) or a master/layout panel
       of ≥ 60 % of the slide containing the body region — never a placeholder, a text box or a freeform (its box is
       not what it paints). A picture gives kind «image» and its median colour; a semi-opaque veil is blended with
       what lies under it. A master/layout picture or panel that only textures the `p:bg` colour (same family,
       contrast < 1.2:1) leaves the `p:bg` colour in place. The slide's own panels are cards (content frames), not
       the ground.
    2. The `p:bg` chain (slide → layout → master).
    3. No `p:bg` at all: white (what PowerPoint paints). A picture `p:bg` that cannot be read: the render's median
       colour, else the majority text colour decides the family.
    """
    slide_w, slide_h = package.slide_size
    slide_area = float(slide_w * slide_h)
    whole = Bbox(x=0, y=0, w=slide_w, h=slide_h)
    layers = painted_layers(package, slide_part, ctx)
    bg_hex, bg_kind = _bg_chain(package, slide_part, ctx)
    body = _body_region(shapes, slide_w, slide_h)

    def ground_like(la: PaintedLayer) -> bool:
        if not la.opaque or not la.hex or la.placeholder or la.has_text or la.custom_geom:
            return False
        if la.box.intersection(whole) >= _FULL_BLEED * slide_area:
            return True
        return la.source != "slide" and la.kind != "image" and la.box.area >= 0.6 * slide_area and la.box.intersection(body) >= 0.8 * max(body.area, 1)

    cands = sorted((la for la in layers if ground_like(la)), key=lambda la: la.z)
    if cands:
        top = cands[-1]
        hx = top.hex
        if top.alpha < 0.98:
            # a veil: blended with the topmost full-bleed paint under it (a filled placeholder counts: it paints)
            under = next((la.hex for la in sorted(layers, key=lambda la: -la.z) if la.z < top.z and la.opaque and la.alpha >= 0.98 and la.hex and not la.custom_geom and la.box.intersection(whole) >= _FULL_BLEED * slide_area), None)
            hx = _blend(under or bg_hex or "FFFFFF", hx, top.alpha)
        textures_bg = (
            (top.source != "slide" or top.kind == "image")
            and bg_hex is not None
            and bg_kind != "image"
            and _family_of(hx) == _family_of(bg_hex)
            and contrast_ratio(hx, bg_hex) < _SAME_GROUND
        )
        if not textures_bg:
            cover = top.box.intersection(whole) / slide_area
            src = f"layer:{top.source}" if cover >= _FULL_BLEED else "panel"
            return GroundInfo(_family_of(hx), hx, top.kind, uncertain=top.busy or top.kind == "gradient", source=src, cover=round(cover, 3), bg_hex=bg_hex)
    if bg_kind and bg_hex:
        return GroundInfo(_family_of(bg_hex), bg_hex, bg_kind, uncertain=bg_kind == "image", source="bg")
    if bg_kind is None:
        # no p:bg anywhere and no layer paints the slide: PowerPoint paints it white (a render's median would
        # mistake the template's art — Focus's coloured triangles — for the ground)
        return GroundInfo(Family.light, "FFFFFF", "solid", uncertain=False, source="default")
    if image_path:
        try:
            from PIL import Image

            with Image.open(image_path) as im:
                small = im.convert("L").resize((32, 18))
                mean = sum(small.tobytes()) / (32 * 18)
                rgb = im.convert("RGB").resize((32, 18))
                chans = [sorted(rgb.getchannel(c).tobytes()) for c in range(3)]
            median = "".join(f"{ch[len(ch) // 2]:02X}" for ch in chans)
            # the render's median colour stands for the ground in contrast decisions (LCT purple photos)
            return GroundInfo(Family.dark if mean < 90 else Family.light, median, bg_kind or "render", uncertain=True, source="render")
        except Exception:  # noqa: BLE001
            pass
    # a picture ground we could not read: fall back to the majority text colour (light text → dark slide)
    lum = [relative_luminance(s.text.dominant_color) for s in shapes if s.text and s.text.dominant_color]
    if lum and sum(1 for v in lum if v > 0.6) > len(lum) / 2:
        return GroundInfo(Family.dark, None, bg_kind, uncertain=True, source="text")
    return GroundInfo(Family.light, None, bg_kind, uncertain=True, source="text")


# ---------------------------------------------------------------------------- free room left by the template's art


def art_boxes(layers: list[PaintedLayer], slide_w: int, slide_h: int, sources: tuple[str, ...] = ("master", "layout")) -> list[Bbox]:
    """Boxes of the template's art on a slide: painted shapes and pictures of the given layers that are not grounds
    (a calm full-bleed ground, a panel of ≥ 60 % of the slide), not placeholders, not rules (≤ 2 % H high) and not
    specks (< 0.3 % of the slide)."""
    area = float(slide_w * slide_h)
    whole = Bbox(x=0, y=0, w=slide_w, h=slide_h)
    out = []
    for la in layers:
        if la.source not in sources or la.placeholder:
            continue
        inside = la.box.intersection(whole)
        if inside < 0.003 * area or min(la.box.h, slide_h) <= 0.02 * slide_h:
            continue
        if inside >= _FULL_BLEED * area and not la.busy and not la.custom_geom:
            continue  # a calm ground
        if la.kind != "image" and not la.custom_geom and inside >= 0.6 * area:
            continue  # a panel the content stands on
        out.append(la.box)
    return out


def largest_free_share(obstacles: list[Bbox], area: Bbox, grid: tuple[int, int] = (64, 36)) -> float:
    """Share of `area` taken by the largest axis-aligned rectangle that no obstacle touches (coarse grid)."""
    gw, gh = grid
    if area.w <= 0 or area.h <= 0:
        return 0.0
    cw, ch = area.w / gw, area.h / gh
    blocked = [[False] * gw for _ in range(gh)]
    for b in obstacles:
        x0 = int(max(0, (b.x - area.x) / cw))
        x1 = int(min(gw, -(-(b.x2 - area.x) // cw)))
        y0 = int(max(0, (b.y - area.y) / ch))
        y1 = int(min(gh, -(-(b.y2 - area.y) // ch)))
        for yy in range(y0, y1):
            row = blocked[yy]
            for xx in range(x0, x1):
                row[xx] = True
    heights = [0] * gw
    best = 0
    for yy in range(gh):
        for xx in range(gw):
            heights[xx] = 0 if blocked[yy][xx] else heights[xx] + 1
        stack: list[int] = []
        for xx in range(gw + 1):
            hcur = heights[xx] if xx < gw else 0
            while stack and heights[stack[-1]] >= hcur:
                top = stack.pop()
                width = xx if not stack else xx - stack[-1] - 1
                best = max(best, heights[top] * width)
            stack.append(xx)
    return round(best / float(gw * gh), 3)
