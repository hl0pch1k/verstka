"""Extract shapes (geometry, style, text with inherited properties) from a slide part."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from lxml import etree

from verstka.analysis.theme import ThemeResolver
from verstka.analysis.xmlns import NS, attr_bool, attr_int, find, find_first, findall, local_name, q
from verstka.ingest.package import PptxPackage
from verstka.schemas.common import Bbox, Family, ShapeKind, relative_luminance

# ---------------------------------------------------------------------------- data


@dataclass
class RunInfo:
    text: str
    font: Optional[str] = None
    size_pt: Optional[float] = None
    bold: bool = False
    italic: bool = False
    color_hex: Optional[str] = None


@dataclass
class ParagraphInfo:
    text: str
    level: int = 0
    has_bullet: bool = False
    align: Optional[str] = None  # l, ctr, r, just
    runs: list[RunInfo] = field(default_factory=list)
    line_spacing: Optional[float] = None
    space_after_pt: Optional[float] = None

    @property
    def size_pt(self) -> Optional[float]:
        sizes = [r.size_pt for r in self.runs if r.size_pt]
        return max(sizes) if sizes else None


@dataclass
class TextInfo:
    paragraphs: list[ParagraphInfo] = field(default_factory=list)
    autofit: Optional[str] = None  # norm, sp, none
    anchor: Optional[str] = None  # t, ctr, b
    wrap: bool = True
    insets_emu: tuple[int, int, int, int] = (91440, 45720, 91440, 45720)  # l, t, r, b

    @property
    def plain(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)

    @property
    def n_chars(self) -> int:
        return sum(len(p.text) for p in self.paragraphs)

    @property
    def max_size_pt(self) -> Optional[float]:
        sizes = [p.size_pt for p in self.paragraphs if p.size_pt]
        return max(sizes) if sizes else None

    @property
    def dominant_size_pt(self) -> Optional[float]:
        weights: dict[float, int] = {}
        for p in self.paragraphs:
            for r in p.runs:
                if r.size_pt:
                    weights[r.size_pt] = weights.get(r.size_pt, 0) + max(len(r.text), 1)
        return max(weights, key=weights.get) if weights else None

    @property
    def bold_share(self) -> float:
        total = 0
        bold = 0
        for p in self.paragraphs:
            for r in p.runs:
                n = len(r.text)
                total += n
                if r.bold:
                    bold += n
        return bold / total if total else 0.0

    @property
    def dominant_font(self) -> Optional[str]:
        weights: dict[str, int] = {}
        for p in self.paragraphs:
            for r in p.runs:
                if r.font:
                    weights[r.font] = weights.get(r.font, 0) + max(len(r.text), 1)
        return max(weights, key=weights.get) if weights else None

    @property
    def dominant_color(self) -> Optional[str]:
        weights: dict[str, int] = {}
        for p in self.paragraphs:
            for r in p.runs:
                if r.color_hex:
                    weights[r.color_hex] = weights.get(r.color_hex, 0) + max(len(r.text), 1)
        return max(weights, key=weights.get) if weights else None

    @property
    def dominant_align(self) -> Optional[str]:
        weights: dict[str, int] = {}
        for p in self.paragraphs:
            a = p.align or "l"
            weights[a] = weights.get(a, 0) + max(len(p.text), 1)
        return max(weights, key=weights.get) if weights else None

    @property
    def has_bullets(self) -> bool:
        return any(p.has_bullet for p in self.paragraphs)


@dataclass
class ShapeInfo:
    id: str
    name: str
    kind: ShapeKind
    bbox: Bbox
    z: int
    rotation: float = 0.0
    group_path: list[str] = field(default_factory=list)
    is_placeholder: bool = False
    ph_type: Optional[str] = None
    ph_idx: Optional[str] = None
    geometry: Optional[str] = None
    fill_hex: Optional[str] = None
    fill_alpha: float = 1.0  # opacity of the solid fill (a:alpha/@val ÷ 100000), 1.0 when opaque
    line_hex: Optional[str] = None
    line_w_emu: Optional[int] = None
    corner_radius: Optional[float] = None
    has_shadow: bool = False
    image_part: Optional[str] = None
    image_ext: Optional[str] = None
    crop: Optional[tuple[float, float, float, float]] = None
    text: Optional[TextInfo] = None
    frame_kind: Optional[Literal["table", "chart", "diagram", "ole", "other"]] = None
    table_dims: Optional[tuple[int, int]] = None
    element: Optional[etree._Element] = field(default=None, repr=False, compare=False)

    @property
    def has_text(self) -> bool:
        return self.text is not None and bool(self.text.plain.strip())

    @property
    def plain_text(self) -> str:
        return self.text.plain if self.text else ""

    @property
    def is_image(self) -> bool:
        return self.kind == ShapeKind.pic

    @property
    def is_visual_shape(self) -> bool:
        """A drawn shape with a fill or a line (not an invisible text box)."""
        return self.kind == ShapeKind.sp and (self.fill_hex is not None or self.line_hex is not None)

    def __hash__(self) -> int:
        return hash((self.id, self.z))


# ---------------------------------------------------------------------------- transforms


@dataclass
class _Xform:
    """Maps child coordinates of a group to slide coordinates."""

    off_x: int = 0
    off_y: int = 0
    ch_off_x: int = 0
    ch_off_y: int = 0
    sx: float = 1.0
    sy: float = 1.0

    def apply(self, x: int, y: int, w: int, h: int) -> tuple[int, int, int, int]:
        nx = self.off_x + (x - self.ch_off_x) * self.sx
        ny = self.off_y + (y - self.ch_off_y) * self.sy
        return round(nx), round(ny), round(w * self.sx), round(h * self.sy)

    def compose(self, child: "_Xform") -> "_Xform":
        """Return transform for elements inside `child` group nested inside self."""
        # child maps its children to its own parent's space; then self maps into slide space
        ox, oy, _, _ = self.apply(child.off_x, child.off_y, 0, 0)
        return _Xform(off_x=ox, off_y=oy, ch_off_x=child.ch_off_x, ch_off_y=child.ch_off_y, sx=self.sx * child.sx, sy=self.sy * child.sy)


def _read_xfrm(xfrm: Optional[etree._Element]) -> Optional[tuple[int, int, int, int, float]]:
    if xfrm is None:
        return None
    off = find(xfrm, "a:off")
    ext = find(xfrm, "a:ext")
    if off is None or ext is None:
        return None
    rot = attr_int(xfrm, "rot", 0) or 0
    return (attr_int(off, "x", 0) or 0, attr_int(off, "y", 0) or 0, attr_int(ext, "cx", 0) or 0, attr_int(ext, "cy", 0) or 0, rot / 60000.0)


def _group_xform(grp: etree._Element) -> _Xform:
    xfrm = find(grp, "p:grpSpPr/a:xfrm")
    if xfrm is None:
        return _Xform()
    off = find(xfrm, "a:off")
    ext = find(xfrm, "a:ext")
    ch_off = find(xfrm, "a:chOff")
    ch_ext = find(xfrm, "a:chExt")
    ox, oy = attr_int(off, "x", 0) or 0, attr_int(off, "y", 0) or 0
    ex, ey = attr_int(ext, "cx", 0) or 0, attr_int(ext, "cy", 0) or 0
    cox, coy = attr_int(ch_off, "x", ox) or 0, attr_int(ch_off, "y", oy) or 0
    cex, cey = attr_int(ch_ext, "cx", ex) or 0, attr_int(ch_ext, "cy", ey) or 0
    sx = ex / cex if cex else 1.0
    sy = ey / cey if cey else 1.0
    return _Xform(ox, oy, cox, coy, sx, sy)


# ---------------------------------------------------------------------------- placeholder lookup


def _ph_of(sp: etree._Element) -> Optional[etree._Element]:
    return find_first(sp, "p:nvSpPr/p:nvPr/p:ph", "p:nvPicPr/p:nvPr/p:ph", "p:nvGraphicFramePr/p:nvPr/p:ph", "p:nvCxnSpPr/p:nvPr/p:ph")


def _placeholders(root: etree._Element) -> list[tuple[str, Optional[str], etree._Element]]:
    """(type, idx, element) for every placeholder shape in a slide/layout/master part."""
    out = []
    for sp in root.iter(q("p:sp")):
        ph = _ph_of(sp)
        if ph is not None:
            out.append(((ph.get("type") or "body"), ph.get("idx"), sp))
    return out


def _match_placeholder(phs: list[tuple[str, Optional[str], etree._Element]], ph_type: str, ph_idx: Optional[str]) -> Optional[etree._Element]:
    # exact idx match first (idx is the primary key for body placeholders), then type match
    if ph_idx is not None:
        for t, i, el in phs:
            if i == ph_idx and (t == ph_type or ph_type in ("body", "obj") and t in ("body", "obj")):
                return el
        for t, i, el in phs:
            if i == ph_idx:
                return el
    type_aliases = {"ctrTitle": ("ctrTitle", "title"), "title": ("title", "ctrTitle"), "subTitle": ("subTitle", "body"), "obj": ("obj", "body"), "body": ("body", "obj")}
    for cand in type_aliases.get(ph_type, (ph_type,)):
        for t, i, el in phs:
            if t == cand:
                return el
    return None


# ---------------------------------------------------------------------------- text style chain


class _StyleChain:
    """Ordered list of lstStyle-like elements to search for level properties."""

    def __init__(self, resolver: ThemeResolver, sources: list[etree._Element], is_title: bool) -> None:
        self.resolver = resolver
        self.sources = [s for s in sources if s is not None]
        self.is_title = is_title

    def level_props(self, level: int) -> list[etree._Element]:
        out = []
        for src in self.sources:
            # every lvlNpPr of a list style, in order: a style written twice for one level (size in the first, colour
            # in the second) is merged by the office suites, so both count
            out.extend(findall(src, f"a:lvl{level + 1}pPr"))
        return out

    def def_rpr(self, level: int) -> list[etree._Element]:
        return [d for lvl in self.level_props(level) if (d := find(lvl, "a:defRPr")) is not None]


def _pt(sz: Optional[int]) -> Optional[float]:
    return sz / 100.0 if sz else None


def _run_props(rpr: Optional[etree._Element], resolver: ThemeResolver) -> dict:
    out: dict = {}
    if rpr is None:
        return out
    if rpr.get("sz"):
        out["size_pt"] = _pt(attr_int(rpr, "sz"))
    if rpr.get("b") is not None:
        out["bold"] = attr_bool(rpr, "b", False)
    if rpr.get("i") is not None:
        out["italic"] = attr_bool(rpr, "i", False)
    latin = find(rpr, "a:latin")
    if latin is not None and latin.get("typeface"):
        out["font"] = resolver.font_for(latin.get("typeface"))
    color = resolver.resolve_fill(rpr)
    if color:
        out["color_hex"] = color
    return out


def _has_bullet(ppr: Optional[etree._Element]) -> Optional[bool]:
    if ppr is None:
        return None
    if find(ppr, "a:buNone") is not None:
        return False
    if find(ppr, "a:buChar") is not None or find(ppr, "a:buAutoNum") is not None or find(ppr, "a:buBlip") is not None:
        return True
    return None


def _parse_text(txBody: etree._Element, chain: _StyleChain, resolver: ThemeResolver, is_title: bool) -> TextInfo:
    body_pr = find(txBody, "a:bodyPr")
    info = TextInfo()
    if body_pr is not None:
        info.anchor = body_pr.get("anchor")
        info.wrap = (body_pr.get("wrap") or "square") != "none"
        info.insets_emu = (
            attr_int(body_pr, "lIns", 91440) or 0,
            attr_int(body_pr, "tIns", 45720) or 0,
            attr_int(body_pr, "rIns", 91440) or 0,
            attr_int(body_pr, "bIns", 45720) or 0,
        )
        if find(body_pr, "a:normAutofit") is not None:
            info.autofit = "norm"
        elif find(body_pr, "a:spAutoFit") is not None:
            info.autofit = "sp"
        elif find(body_pr, "a:noAutofit") is not None:
            info.autofit = "none"
    for p in findall(txBody, "a:p"):
        ppr = find(p, "a:pPr")
        level = attr_int(ppr, "lvl", 0) or 0
        lvl_props = chain.level_props(level)
        align = (ppr.get("algn") if ppr is not None else None) or next((l.get("algn") for l in lvl_props if l.get("algn")), None)
        bullet = _has_bullet(ppr)
        if bullet is None:
            for l in lvl_props:
                b = _has_bullet(l)
                if b is not None:
                    bullet = b
                    break
        if bullet is None:
            bullet = False
        # inherited run defaults (first chain hit wins per attribute)
        inherited: dict = {}
        for d in chain.def_rpr(level):
            for k, v in _run_props(d, resolver).items():
                inherited.setdefault(k, v)
        end_rpr = find(p, "a:endParaRPr")
        para_default = _run_props(find(ppr, "a:defRPr"), resolver)
        runs: list[RunInfo] = []
        texts: list[str] = []
        for child in p:
            tag = local_name(child)
            if tag in ("r", "fld"):
                t_el = find(child, "a:t")
                text = t_el.text if t_el is not None and t_el.text else ""
                props = {**inherited, **para_default, **_run_props(find(child, "a:rPr"), resolver)}
                runs.append(RunInfo(text=text, font=props.get("font"), size_pt=props.get("size_pt"), bold=bool(props.get("bold", False)),
                                    italic=bool(props.get("italic", False)), color_hex=props.get("color_hex")))
                texts.append(text)
            elif tag == "br":
                texts.append("\n")
        if not runs:
            props = {**inherited, **para_default, **_run_props(end_rpr, resolver)}
            runs.append(RunInfo(text="", font=props.get("font"), size_pt=props.get("size_pt"), bold=bool(props.get("bold", False)),
                                italic=bool(props.get("italic", False)), color_hex=props.get("color_hex")))
        # fill defaults for size/font/colour from theme when still missing
        for r in runs:
            if r.size_pt is None:
                r.size_pt = 18.0
            if r.font is None:
                r.font = resolver.major_font if is_title else resolver.minor_font
            if r.color_hex is None:
                r.color_hex = resolver.scheme_hex("tx1") or "000000"
        ln = find(ppr, "a:lnSpc/a:spcPct")
        line_spacing = (attr_int(ln, "val", 100000) or 100000) / 100000.0 if ln is not None else None
        sa = find(ppr, "a:spcAft/a:spcPts")
        space_after = (attr_int(sa, "val", 0) or 0) / 100.0 if sa is not None else None
        info.paragraphs.append(ParagraphInfo(text="".join(texts), level=level, has_bullet=bullet, align=align, runs=runs, line_spacing=line_spacing, space_after_pt=space_after))
    return info


# ---------------------------------------------------------------------------- extraction


class SlideContext:
    """Per-slide lookup helpers: layout/master placeholders and style chains."""

    def __init__(self, package: PptxPackage, slide_part: str) -> None:
        self.package = package
        self.slide_part = slide_part
        self.layout_part = package.layout_of(slide_part)
        self.master_part = package.master_of(self.layout_part) if self.layout_part else (package.master_parts[0] if package.master_parts else None)
        if self.master_part is None:
            raise ValueError(f"{slide_part}: no slide master found")
        self.resolver = ThemeResolver(package, self.master_part)
        self.layout = package.xml(self.layout_part) if self.layout_part else None
        self.master = package.xml(self.master_part)
        self.layout_phs = _placeholders(self.layout) if self.layout is not None else []
        self.master_phs = _placeholders(self.master)
        self.tx_styles = find(self.master, "p:txStyles")

    def master_style_for(self, ph_type: Optional[str], is_placeholder: bool) -> Optional[etree._Element]:
        if self.tx_styles is None:
            return None
        if ph_type in ("title", "ctrTitle"):
            return find(self.tx_styles, "p:titleStyle")
        if is_placeholder:
            return find(self.tx_styles, "p:bodyStyle")
        return find(self.tx_styles, "p:otherStyle")

    def inherited_placeholder(self, ph_type: str, ph_idx: Optional[str]) -> tuple[Optional[etree._Element], Optional[etree._Element]]:
        lay = _match_placeholder(self.layout_phs, ph_type, ph_idx)
        # master placeholder: match by type (idx differs between layout and master)
        mas = _match_placeholder(self.master_phs, ph_type, None)
        return lay, mas


def _bbox_from_sp(sp: etree._Element, spPr_path: str) -> Optional[tuple[int, int, int, int, float]]:
    if spPr_path == "p:xfrm":  # graphicFrame: <p:xfrm><a:off/><a:ext/></p:xfrm>
        return _read_xfrm(find(sp, "p:xfrm"))
    return _read_xfrm(find(sp, f"{spPr_path}/a:xfrm"))


def _extract_one(el: etree._Element, ctx: SlideContext, xform: _Xform, z: int, group_path: list[str]) -> Optional[ShapeInfo]:
    tag = local_name(el)
    resolver = ctx.resolver
    kind_map = {"sp": ShapeKind.sp, "pic": ShapeKind.pic, "graphicFrame": ShapeKind.graphic_frame, "cxnSp": ShapeKind.connector}
    if tag not in kind_map:
        return None
    kind = kind_map[tag]
    nv = find_first(el, "p:nvSpPr/p:cNvPr", "p:nvPicPr/p:cNvPr", "p:nvGraphicFramePr/p:cNvPr", "p:nvCxnSpPr/p:cNvPr")
    sid = (nv.get("id") if nv is not None else None) or f"n{z}"
    name = (nv.get("name") if nv is not None else None) or tag
    ph = _ph_of(el)
    is_ph = ph is not None
    ph_type = (ph.get("type") or "body") if ph is not None else None
    ph_idx = ph.get("idx") if ph is not None else None

    spPr_path = "p:xfrm" if tag == "graphicFrame" else "p:spPr"
    geom = _bbox_from_sp(el, spPr_path)
    lay_ph = mas_ph = None
    if is_ph:
        lay_ph, mas_ph = ctx.inherited_placeholder(ph_type or "body", ph_idx)
        if geom is None and lay_ph is not None:
            geom = _bbox_from_sp(lay_ph, "p:spPr")
        if geom is None and mas_ph is not None:
            geom = _bbox_from_sp(mas_ph, "p:spPr")
    if geom is None:
        geom = (0, 0, 0, 0, 0.0)
    x, y, w, h = xform.apply(*geom[:4])
    bbox = Bbox(x=x, y=y, w=w, h=h)

    info = ShapeInfo(id=sid, name=name, kind=kind, bbox=bbox, z=z, rotation=geom[4], group_path=list(group_path), is_placeholder=is_ph, ph_type=ph_type, ph_idx=ph_idx, element=el)

    spPr = find(el, "p:spPr")
    if spPr is not None:
        prst = find(spPr, "a:prstGeom")
        if prst is not None:
            info.geometry = prst.get("prst")
            if info.geometry in ("roundRect", "round2SameRect", "round1Rect", "snipRoundRect"):
                gd = find(prst, "a:avLst/a:gd")
                info.corner_radius = 0.16667
                if gd is not None and gd.get("fmla", "").startswith("val "):
                    try:
                        info.corner_radius = int(gd.get("fmla").split()[1]) / 100000.0
                    except ValueError:
                        pass
        elif find(spPr, "a:custGeom") is not None:
            info.geometry = "custom"
        if kind != ShapeKind.pic:
            if not resolver.has_no_fill(spPr):
                info.fill_hex = resolver.resolve_fill(spPr)
                alpha = find(spPr, "a:solidFill/*/a:alpha")
                if info.fill_hex is not None and alpha is not None:
                    info.fill_alpha = max(0.0, min(1.0, (attr_int(alpha, "val", 100000) or 0) / 100000.0))
                if info.fill_hex is None and find(spPr, "a:blipFill") is not None:
                    info.fill_hex = None
                    blip = find(spPr, "a:blipFill/a:blip")
                    if blip is not None:
                        rid = blip.get(q("r:embed"))
                        info.image_part = ctx.package.target_of(ctx.slide_part, rid) if rid else None
                if info.fill_hex is None and find(spPr, "a:solidFill") is None and find(spPr, "a:gradFill") is None:
                    # style reference fill (p:style/a:fillRef)
                    fill_ref = find(el, "p:style/a:fillRef")
                    if fill_ref is not None and (attr_int(fill_ref, "idx", 0) or 0) > 0 and len(fill_ref):
                        info.fill_hex = resolver.resolve_color(fill_ref[0])
        ln = find(spPr, "a:ln")
        if ln is not None:
            if find(ln, "a:noFill") is None:
                info.line_hex = resolver.resolve_fill(ln)
                info.line_w_emu = attr_int(ln, "w", 9525)
                if info.line_hex is None and find(ln, "a:solidFill") is None:
                    ln_ref = find(el, "p:style/a:lnRef")
                    if ln_ref is not None and (attr_int(ln_ref, "idx", 0) or 0) > 0 and len(ln_ref):
                        info.line_hex = resolver.resolve_color(ln_ref[0])
        else:
            ln_ref = find(el, "p:style/a:lnRef")
            if ln_ref is not None and (attr_int(ln_ref, "idx", 0) or 0) > 0 and len(ln_ref) and kind == ShapeKind.sp and not is_ph:
                info.line_hex = resolver.resolve_color(ln_ref[0])
                info.line_w_emu = 9525
        if find(spPr, "a:effectLst/a:outerShdw") is not None:
            info.has_shadow = True
        elif find(spPr, "a:effectLst") is None:
            eff = find(el, "p:style/a:effectRef")
            if eff is not None and (attr_int(eff, "idx", 0) or 0) > 0:
                info.has_shadow = True

    if kind == ShapeKind.pic:
        blip = find(el, "p:blipFill/a:blip")
        if blip is not None:
            rid = blip.get(q("r:embed"))
            info.image_part = ctx.package.target_of(ctx.slide_part, rid) if rid else None
            if info.image_part:
                info.image_ext = info.image_part.rsplit(".", 1)[-1].lower()
            svg = find(blip, "a:extLst/a:ext/asvg:svgBlip")
            if svg is not None:
                srid = svg.get(q("r:embed"))
                svg_part = ctx.package.target_of(ctx.slide_part, srid) if srid else None
                if svg_part:
                    info.image_part = svg_part
                    info.image_ext = "svg"
        src = find(el, "p:blipFill/a:srcRect")
        if src is not None:
            info.crop = tuple((attr_int(src, k, 0) or 0) / 100000.0 for k in ("l", "t", "r", "b"))  # type: ignore[assignment]

    if kind == ShapeKind.graphic_frame:
        gd = find(el, "a:graphic/a:graphicData")
        uri = (gd.get("uri") if gd is not None else "") or ""
        if uri.endswith("/table"):
            info.frame_kind = "table"
            tbl = find(gd, "a:tbl")
            if tbl is not None:
                rows = findall(tbl, "a:tr")
                cols = findall(tbl, "a:tblGrid/a:gridCol")
                info.table_dims = (len(rows), len(cols))
                # Google-Slides exports carry a dummy p:xfrm on table frames; the rendered size is the grid
                # (Σ gridCol/@w × Σ tr/@h), so take the larger of the two and keep it inside the slide
                grid_w = sum(attr_int(c, "w", 0) or 0 for c in cols)
                grid_h = sum(attr_int(r, "h", 0) or 0 for r in rows)
                if grid_w > 0 and grid_h > 0:
                    _, _, gw, gh = xform.apply(0, 0, grid_w, grid_h)
                    slide_w, slide_h = ctx.package.slide_size
                    w = max(bbox.w, gw)
                    h = max(bbox.h, gh)
                    if bbox.x < slide_w:
                        w = min(w, slide_w - bbox.x)
                    if bbox.y < slide_h:
                        h = min(h, slide_h - bbox.y)
                    info.bbox = Bbox(x=bbox.x, y=bbox.y, w=max(w, 0), h=max(h, 0))
                # collect cell text as paragraphs for placeholder detection
                ti = TextInfo()
                for tr in rows:
                    for tc in findall(tr, "a:tc"):
                        for p in findall(tc, "a:txBody/a:p"):
                            t = "".join(t.text or "" for t in p.iter(q("a:t")))
                            if t.strip():
                                ti.paragraphs.append(ParagraphInfo(text=t, runs=[RunInfo(text=t, size_pt=12.0, font=resolver.minor_font)]))
                info.text = ti
        elif uri.endswith("/chart"):
            info.frame_kind = "chart"
        elif uri.endswith("/diagram"):
            info.frame_kind = "diagram"
        elif "ole" in uri.lower():
            info.frame_kind = "ole"
        else:
            info.frame_kind = "other"

    txBody = find(el, "p:txBody")
    if txBody is not None and kind == ShapeKind.sp:
        is_title = ph_type in ("title", "ctrTitle")
        sources = [find(txBody, "a:lstStyle")]
        if lay_ph is not None:
            sources.append(find(lay_ph, "p:txBody/a:lstStyle"))
        if mas_ph is not None:
            sources.append(find(mas_ph, "p:txBody/a:lstStyle"))
        sources.append(ctx.master_style_for(ph_type, is_ph))
        chain = _StyleChain(resolver, sources, is_title)
        info.text = _parse_text(txBody, chain, resolver, is_title)
    return info


def _iter_children(tree: etree._Element):
    """Yield drawable children, unwrapping mc:AlternateContent (prefer Fallback)."""
    for child in tree:
        tag = local_name(child)
        if tag == "AlternateContent":
            fb = find(child, "mc:Fallback")
            src = fb if fb is not None else find(child, "mc:Choice")
            if src is not None:
                yield from _iter_children(src)
        else:
            yield child


def extract_shapes(package: PptxPackage, slide_part: str, ctx: Optional[SlideContext] = None) -> list[ShapeInfo]:
    ctx = ctx or SlideContext(package, slide_part)
    root = package.xml(slide_part)
    tree = find(root, "p:cSld/p:spTree")
    out: list[ShapeInfo] = []
    counter = [0]

    def walk(container: etree._Element, xform: _Xform, group_path: list[str]) -> None:
        for child in _iter_children(container):
            tag = local_name(child)
            if tag == "grpSp":
                nv = find(child, "p:nvGrpSpPr/p:cNvPr")
                gid = (nv.get("id") if nv is not None else None) or f"g{counter[0]}"
                walk(child, xform.compose(_group_xform(child)), group_path + [gid])
            elif tag in ("sp", "pic", "graphicFrame", "cxnSp"):
                counter[0] += 1
                info = _extract_one(child, ctx, xform, counter[0], group_path)
                if info is not None:
                    out.append(info)

    if tree is not None:
        walk(tree, _Xform(), [])
    return out


# ---------------------------------------------------------------------------- family


def _bg_hex(root: etree._Element, resolver: ThemeResolver) -> tuple[Optional[str], Optional[str]]:
    """(hex, kind) from a p:bg element under cSld; kind ∈ solid/gradient/image/none."""
    bg = find(root, "p:cSld/p:bg")
    if bg is None:
        return None, None
    bgpr = find(bg, "p:bgPr")
    if bgpr is not None:
        if find(bgpr, "a:blipFill") is not None:
            return None, "image"
        if find(bgpr, "a:gradFill") is not None:
            return resolver.resolve_fill(bgpr), "gradient"
        return resolver.resolve_fill(bgpr), "solid"
    ref = find(bg, "p:bgRef")
    if ref is not None and len(ref):
        return resolver.resolve_color(ref[0]), "solid"
    return None, None


def slide_background(package: PptxPackage, slide_part: str, ctx: SlideContext) -> tuple[Optional[str], Optional[str]]:
    """(hex, kind) of the first p:bg of slide → layout → master; (None, None) when no part defines one (the slide
    is then white unless a layer paints it: see `ground.slide_ground`)."""
    for part_root in (package.xml(slide_part), ctx.layout, ctx.master):
        if part_root is None:
            continue
        hex_, kind = _bg_hex(part_root, ctx.resolver)
        if kind:
            return hex_, kind
    return None, None


_BG_COLOR_CACHE: dict[tuple, Optional[str]] = {}


def background_picture_color(package: PptxPackage, slide_part: str, ctx: SlideContext) -> Optional[str]:
    """Median colour of the picture a slide's background is filled with (slide → layout → master), or None.

    The rendered slide mixes the ground with its cards; the picture itself is what text and tables stand on."""
    for part in (slide_part, ctx.layout_part, ctx.master_part):
        if not part:
            continue
        root = package.xml(part)
        blip = find(root, "p:cSld/p:bg/p:bgPr/a:blipFill/a:blip")
        if blip is None:
            if find(root, "p:cSld/p:bg") is not None:
                return None  # a solid or gradient ground wins over the parts below
            continue
        target = package.target_of(part, blip.get(q("r:embed")) or "")
        if not target or not package.exists(target):
            return None
        from verstka.analysis.ground import package_key

        key = (package_key(package), target)
        if key not in _BG_COLOR_CACHE:
            try:
                from io import BytesIO

                from PIL import Image

                with Image.open(BytesIO(package.read(target))) as im:
                    rgb = im.convert("RGB").resize((48, 27))
                    chans = [sorted(rgb.getchannel(c).tobytes()) for c in range(3)]
                _BG_COLOR_CACHE[key] = "".join(f"{ch[len(ch) // 2]:02X}" for ch in chans)
            except Exception:  # noqa: BLE001
                _BG_COLOR_CACHE[key] = None
        return _BG_COLOR_CACHE[key]
    return None


def slide_family(package: PptxPackage, slide_part: str, ctx: SlideContext, shapes: list[ShapeInfo], image_path: Optional[str] = None) -> tuple[Family, Optional[str]]:
    """Light/dark family and the effective background hex (None when unknown).

    The ground is what the slide really stands on — a full-bleed picture or panel of the master, the layout or the
    slide, a panel under the body, else the p:bg chain (see `ground.slide_ground`)."""
    from verstka.analysis.ground import slide_ground

    g = slide_ground(package, slide_part, ctx, shapes, image_path)
    return g.family, g.hex


PLACEHOLDER_RE = re.compile(
    r"lorem|ipsum|заголовок в (две|одну)|в две или (в )?одну|вставить\s*(фото|qr)|^x{2,}%?$|xxx|"
    # a speaker's sample name and title: the whole text, or the template's own phrase — never the words inside real
    # content («вступил в должность президента», «имя и фамилия автора указаны…»)
    r"^\s*(имя\s+фамилия|фамилия\s+имя)\b|^\s*должность\s*[.:]?\s*$|должность\s+и\s+регали|"
    r"^\s*(имя|фамилия|должность)(\s*[,\n—-]\s*(имя|фамилия|должность|компания))+\s*$|"
    r"текст описания|^текст$|^описание$|^пункт$|^заголовок$|^подзаголовок$|^название презентации$|^имя спикера|^дата$|^основной текст$|"
    r"^\s*текст\s*$|^показатель$|^примечание$|^заметка$|^ссылка$|^кнопка$|^qr-?code$|^призыв к действию|^call to action$|"
    # English sample copy of third-party templates («DEMO SLIDE», «Title Text Demo», «Slide Title Goes Here»,
    # «Click to edit Master title style», «Put Your Awesome Word In Here»): a specific phrase, never a lone word
    # that a real heading may contain («Demo Day» stays content)
    r"\bdemo\s+(slide|text|title|page|content|copy)\b|\b(title|text|sample|slide|subtitle)\s+(text\s+)?demo\b|^demo$|"
    r"\b(sample|dummy|placeholder)\s+text\b|\btitle\s+text\b|\bclick\s+to\s+(edit|add)\b|\bslide\s+title\b|\bgoes\s+here\b|"
    r"\byour\s+(awesome\s+)?(text|title|logo|word|headline|subtitle|content|company)\b|"
    r"\b(insert|add)\s+(your\s+|an?\s+)?(picture|image|photo|logo)\b|\bcompany\s+name\b|\bspeaker\s+name\b|"
    r"^(image|picture|photo|logo|info text|text style|text here)$",
    re.I,
)


def looks_like_placeholder(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    return bool(PLACEHOLDER_RE.search(t))
