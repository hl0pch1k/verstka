"""Single-file HTML export built from DeckIR: real markup, embedded fonts and images, SVG charts, HTML tables."""

from __future__ import annotations

import base64
import html
import math
import re
from pathlib import Path
from typing import Optional

from lxml import etree

from verstka.audit.ir import build_deck_ir
from verstka.export.svg_charts import chart_svg
from verstka.ingest.package import PptxPackage
from verstka.rendering.fonts import FONT_DIR
from verstka.schemas.common import EMU_PER_PT, contrast_ratio
from verstka.schemas.deck_ir import DeckIR, IRElement, IRSlide
from verstka.schemas.template import TemplateManifest

_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "svg": "image/svg+xml", "webp": "image/webp", "bmp": "image/bmp", "emf": "image/emf", "wmf": "image/wmf"}


def _image_class(pkg: PptxPackage, part: Optional[str], cache: dict[str, str]) -> Optional[str]:
    """Register an image once and return its CSS class name (the data URI lives in a single <style> rule)."""
    if not part or not pkg.exists(part):
        return None
    if part in cache:
        return cache[part] or None
    ext = part.rsplit(".", 1)[-1].lower()
    mime = _MIME.get(ext)
    if mime is None or ext in ("emf", "wmf"):
        cache[part] = ""
        return None
    cls = f"im{len([v for v in cache.values() if v]) + 1}"
    cache[part] = cls
    cache.setdefault("__uris__", {})  # type: ignore[arg-type]
    cache["__uris__"][cls] = f"data:{mime};base64," + base64.b64encode(pkg.read(part)).decode("ascii")  # type: ignore[index]
    return cls


def _font_face() -> str:
    faces = []
    for name, weight in (("Play-Regular.ttf", 400), ("Play-Bold.ttf", 700)):
        p = FONT_DIR / name
        if p.exists():
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
            faces.append(f"@font-face{{font-family:'Play';font-weight:{weight};src:url(data:font/ttf;base64,{b64}) format('truetype');}}")
    return "\n".join(faces)


def _pct(v: float) -> str:
    return f"{v * 100:.3f}%"


def _size_css(size_pt: float, slide_w_emu: int) -> str:
    """Font size relative to the slide width so the slide scales with the viewport (container query units)."""
    slide_w_pt = slide_w_emu / EMU_PER_PT
    return f"{size_pt / slide_w_pt * 100:.4f}cqw"


def _lh(p) -> str:
    """The paragraph's own line spacing (a:lnSpc, 0.9 = 90 %) on top of single spacing (1.2 of the font size), as
    PowerPoint sets it: a title typeset at 90 % keeps its lines inside its frame."""
    ls = getattr(p, "line_spacing", None)
    return f";line-height:{1.2 * ls:.2f}" if ls else ""


def _runs_html(p, slide_w: int, default_color: str, default_font: str) -> str:
    """The paragraph's runs as spans, with its line breaks (<a:br/>) as <br>: the paragraph's text is its runs' texts
    with «\n» where the breaks stand, so walking both puts every break back between the right runs."""
    out: list[str] = []
    text = p.text or ""
    i = 0
    for r in p.runs:
        if not r.text:
            continue
        j = text.find(r.text, i)
        if j >= 0:
            out.extend("<br>" for ch in text[i:j] if ch == "\n")
            i = j + len(r.text)
        out.append(
            f'<span style="font-size:{_size_css(r.size_pt or 14, slide_w)};color:#{r.color_hex or default_color};font-weight:{700 if r.bold else 400};font-style:{"italic" if r.italic else "normal"};font-family:\'{html.escape(r.font or default_font)}\',Play,Arial,sans-serif">{html.escape(r.text)}</span>'
        )
    return "".join(out)


_NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _crop_css(crop) -> str:
    """The visible part of a picture (`a:srcRect` as fractions l, t, r, b of the image) stretched over its frame as
    PowerPoint does: the image drawn larger than the frame and shifted, never the whole of it fitted in (a hard edge
    across a cropped cover). Empty when nothing is cropped."""
    if not crop:
        return ""
    l, t, r, b = crop
    if min(crop) < 0 or max(crop) <= 1e-6 or l + r >= 0.99 or t + b >= 0.99:
        return ""
    px = l / (l + r) * 100 if (l + r) > 1e-9 else 0.0
    py = t / (t + b) * 100 if (t + b) > 1e-9 else 0.0
    return f";background-size:{100 / (1 - l - r):.3f}% {100 / (1 - t - b):.3f}%;background-position:{px:.3f}% {py:.3f}%;background-repeat:no-repeat"


def _layer_pictures(pkg: PptxPackage, part: str, slide_w: int, slide_h: int) -> list[dict]:
    """The pictures a layout or a master really holds — as the deck has them (a brand's logo moved into its corner, a
    template picture cropped): (image part, frame as fractions of the slide, crop). Placeholders and hidden shapes are not
    drawn on a slide; pictures inside groups are placed through their groups' transforms. Rotated or flipped ones are drawn
    unrotated in their frame."""
    out: list[dict] = []
    try:
        tree = pkg.xml(part).find("p:cSld/p:spTree", _NS)
    except Exception:  # noqa: BLE001
        return out
    if tree is None:
        return out

    def walk(el, m: tuple[float, float, float, float]) -> None:
        sx, sy, tx, ty = m
        for ch in el:
            if not isinstance(ch.tag, str):
                continue
            name = etree.QName(ch).localname
            if name == "grpSp":
                xf = ch.find("p:grpSpPr/a:xfrm", _NS)
                if xf is None:
                    continue
                off, ext, c_off, c_ext = xf.find("a:off", _NS), xf.find("a:ext", _NS), xf.find("a:chOff", _NS), xf.find("a:chExt", _NS)
                if None in (off, ext, c_off, c_ext) or int(c_ext.get("cx") or 0) == 0 or int(c_ext.get("cy") or 0) == 0:
                    continue
                gx, gy = int(ext.get("cx")) / int(c_ext.get("cx")), int(ext.get("cy")) / int(c_ext.get("cy"))
                walk(ch, (sx * gx, sy * gy, tx + sx * (int(off.get("x")) - int(c_off.get("x")) * gx), ty + sy * (int(off.get("y")) - int(c_off.get("y")) * gy)))
            elif name == "pic":
                c_nv = ch.find("p:nvPicPr/p:cNvPr", _NS)
                if ch.find("p:nvPicPr/p:nvPr/p:ph", _NS) is not None or (c_nv is not None and c_nv.get("hidden") in ("1", "true")):
                    continue
                blip = ch.find("p:blipFill/a:blip", _NS)
                rid = blip.get(f"{{{_NS['r']}}}embed") if blip is not None else None
                image = pkg.target_of(part, rid) if rid else None
                xf = ch.find("p:spPr/a:xfrm", _NS)
                if not image or xf is None or xf.find("a:off", _NS) is None or xf.find("a:ext", _NS) is None:
                    continue
                x, y = tx + sx * int(xf.find("a:off", _NS).get("x")), ty + sy * int(xf.find("a:off", _NS).get("y"))
                w, h = sx * int(xf.find("a:ext", _NS).get("cx")), sy * int(xf.find("a:ext", _NS).get("cy"))
                rect = ch.find("p:blipFill/a:srcRect", _NS)
                crop = tuple(int(rect.get(k) or 0) / 100000.0 for k in ("l", "t", "r", "b")) if rect is not None else None
                out.append({"image": image, "x": x / slide_w, "y": y / slide_h, "w": w / slide_w, "h": h / slide_h, "crop": crop if crop and any(crop) else None})

    walk(tree, (1.0, 1.0, 0.0, 0.0))
    return out


def _slide_facts(pkg: PptxPackage, slide_part: Optional[str], slide_w: int) -> dict[str, dict]:
    """What the IR does not carry, read from the slide's own XML per shape id: the drop shadow (CSS `box-shadow`) and, for
    a chart, whether its series has a trend line."""
    out: dict[str, dict] = {}
    if not slide_part:
        return out
    try:
        root = pkg.xml(slide_part)
    except Exception:  # noqa: BLE001
        return out
    for sp in list(root.iterfind(".//p:sp", _NS)) + list(root.iterfind(".//p:graphicFrame", _NS)):
        c_nv = sp.find("p:nvSpPr/p:cNvPr", _NS)
        if c_nv is None:
            c_nv = sp.find("p:nvGraphicFramePr/p:cNvPr", _NS)
        if c_nv is None:
            continue
        info: dict = {}
        sh = sp.find("p:spPr/a:effectLst/a:outerShdw", _NS)
        if sh is not None:
            clr = sh.find("a:srgbClr", _NS)
            if clr is not None and clr.get("val"):
                alpha = clr.find("a:alpha", _NS)
                a = int(alpha.get("val")) / 100000.0 if alpha is not None else 1.0
                ang = math.radians(int(sh.get("dir") or 0) / 60000.0)
                dist, blur = int(sh.get("dist") or 0), int(sh.get("blurRad") or 0)
                cq = lambda v: f"{v / max(slide_w, 1) * 100:.3f}cqw"  # noqa: E731
                info["shadow"] = f"{cq(dist * math.cos(ang))} {cq(dist * math.sin(ang))} {cq(blur)} {_rgba(clr.get('val'), a)}"
        chart = sp.find(".//c:chart", _NS)
        if chart is not None:
            rid = chart.get(f"{{{_NS['r']}}}id")
            part = pkg.target_of(slide_part, rid) if rid else None
            if part and pkg.exists(part):
                try:
                    info["trend"] = pkg.xml(part).find(".//c:trendline", _NS) is not None
                except Exception:  # noqa: BLE001
                    pass
        if info:
            out[c_nv.get("id")] = info
    return out


def _rgba(hex_: str, alpha: float) -> str:
    """`#RRGGBB` at `alpha` as CSS (a translucent swatch keeps the tint PowerPoint composites over the slide)."""
    if alpha >= 0.999 or len(hex_) != 6:
        return f"#{hex_}"
    r, g, b = int(hex_[0:2], 16), int(hex_[2:4], 16), int(hex_[4:6], 16)
    return f"rgba({r},{g},{b},{alpha:.3f})"


def _inset_css(e: IRElement, slide_w: int) -> str:
    """The text frame's own insets (a:bodyPr lIns…), as the slide's width share — a text box with none (0) keeps its
    whole width for its text: «46%» in a 38 pt box stays on one line; a figure in a box as tall as its line is not
    pushed out of it by padding the PowerPoint box never had."""
    l, t, r, b = e.insets_emu
    return ";".join(f"padding-{side}:{v / max(slide_w, 1) * 100:.3f}cqw" for side, v in (("top", t), ("right", r), ("bottom", b), ("left", l)))


def _text_html(e: IRElement, slide_w: int, default_color: str, default_font: str) -> str:
    align = {"ctr": "center", "r": "right", "just": "justify"}.get(e.paragraphs[0].align or "", "left") if e.paragraphs else "left"
    vpos = {"ctr": "center", "b": "flex-end"}.get(e.anchor or "t", "flex-start")
    inner = []
    in_list = False
    for p in e.paragraphs:
        runs = _runs_html(p, slide_w, default_color, default_font) or "&nbsp;"
        if p.bullet:
            if not in_list:
                inner.append("<ul>")
                in_list = True
            inner.append(f'<li style="margin-left:{p.level * 1.2}em{_lh(p)}">{runs}</li>')
        else:
            if in_list:
                inner.append("</ul>")
                in_list = False
            inner.append(f'<p style="text-align:{align}{_lh(p)}">{runs}</p>')
    if in_list:
        inner.append("</ul>")
    nowrap = "" if e.wrap else ";white-space:nowrap"
    return f'<div class="tx" style="justify-content:{vpos};{_inset_css(e, slide_w)}{nowrap}">{"".join(inner)}</div>'


def _shape_css(e: IRElement, slide_w: int, slide_h: int, shadow: Optional[str] = None) -> str:
    css = []
    if shadow:
        css.append(f"box-shadow:{shadow}")
    if e.fill_hex:
        css.append(f"background:{_rgba(e.fill_hex, e.fill_alpha)}")
    if e.line_hex:
        css.append(f"border:1px solid #{e.line_hex}")
    if e.geometry == "ellipse":
        css.append("border-radius:50%")
    elif e.corner_radius:
        r = e.corner_radius * min(e.bbox.w, e.bbox.h) / slide_w * 100
        css.append(f"border-radius:{r:.2f}cqw")
    if e.rotation:
        css.append(f"transform:rotate({e.rotation:.1f}deg)")
    return ";".join(css)


_NUMBER_CELL = re.compile(
    r"[−+\-–]?\d[\d\s\u00a0\u202f.,]*\s*(?:%|п\.\s?п\.|×|x|₽|\$|€|руб\.?|тыс\.?|млн|млрд|трлн|чел\.?|шт\.?|мин\.?|ч\.?)*(?:\s*(?:₽|\$|€|руб\.?))?"
)


def _number_columns(rows: list[list[str]]) -> list[bool]:
    """Which columns of a table are numbers (every body cell a figure with its unit, «1 433», «+38%», «423 млн ₽»): they
    are right-aligned under their right-aligned headers, a column of words stays left-aligned under its header."""
    width = max((len(r) for r in rows), default=0)
    out = []
    for j in range(width):
        cells = [" ".join((r[j] if j < len(r) else "").split()) for r in rows[1:]]
        cells = [c for c in cells if c and c not in ("—", "-", "–")]
        out.append(bool(cells) and all(_NUMBER_CELL.fullmatch(c) for c in cells))
    return out


def _element_html(e: IRElement, slide: IRSlide, ir: DeckIR, pkg: PptxPackage, cache: dict, manifest: TemplateManifest, default_font: str, facts: Optional[dict] = None) -> str:
    info = (facts or {}).get(str(e.id), {})
    f = e.bbox_frac
    style = f"left:{_pct(f.x)};top:{_pct(f.y)};width:{_pct(f.w)};height:{_pct(f.h)};z-index:{e.z}"
    bg = slide.background_hex or ("000000" if slide.family.value == "dark" else "FFFFFF")
    text_default = manifest.tokens.color_for("text.primary") or "000000"
    if contrast_ratio(text_default, bg) < 2.5:
        text_default = "FFFFFF" if slide.family.value == "dark" else "000000"
    if e.type == "picture":
        cls = _image_class(pkg, e.image_part, cache)
        if not cls:
            return ""
        if e.formula:  # a formula: its picture as drawn (its box is the picture's own), read aloud as its text
            return f'<div class="el pic {cls}" role="img" aria-label="{html.escape(e.formula, quote=True)}" style="{style};background-size:100% 100%"></div>'
        return f'<div class="el pic {cls}" style="{style}{_crop_css(e.crop)}"></div>'
    if e.type == "chart" and e.chart:
        colors = manifest.components.chart_style.series_colors or manifest.tokens.accents()
        # the slide's text box «Chart legend title» (the group the legend's series belong to) stands at the head of the
        # legend's row: the legend begins after it
        legend_left = 0.0
        for t in slide.elements:
            if t.name == "Chart legend title" and e.bbox.x - 1 <= t.bbox.x <= e.bbox.x + e.bbox.w and e.bbox.y + 0.6 * e.bbox.h <= t.bbox.y <= e.bbox.y + e.bbox.h:
                legend_left = max(legend_left, (t.bbox.x + t.bbox.w - e.bbox.x) / EMU_PER_PT)
        svg = chart_svg(e.chart, e.bbox.w / EMU_PER_PT, e.bbox.h / EMU_PER_PT, colors, text_hex=text_default, font=f"'{default_font}', Play, Arial, sans-serif", font_px=max(manifest.components.chart_style.font_size_pt, 9), ground=bg, legend_left=legend_left, trend=bool(info.get("trend")))
        return f'<div class="el" style="{style}">{svg}</div>'
    if e.type == "table" and e.table and e.table.rows:
        ts = manifest.components.table_style
        rows = e.table.rows
        num = _number_columns(rows)
        head = "".join(f'<th{" class=n" if num[j] else ""} style="background:#{e.table.header_fill_hex or ts.header_fill_hex or "0077FF"};color:#{ts.header_text_hex or "FFFFFF"}">{html.escape(c)}</th>' for j, c in enumerate(rows[0]))
        body = "".join("<tr>" + "".join(f'<td{" class=n" if num[j] else ""}>{html.escape(c)}</td>' for j, c in enumerate(r)) + "</tr>" for r in rows[1:])
        return f'<div class="el" style="{style}"><table style="font-size:{_size_css(ts.font_size_pt, ir.slide_w)};color:#{ts.body_text_hex or text_default}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
    if e.type in ("text", "shape"):
        box = _shape_css(e, ir.slide_w, ir.slide_h, info.get("shadow"))
        inner = _text_html(e, ir.slide_w, text_default, default_font) if e.has_text else ""
        return f'<div class="el txt" style="{style};{box}">{inner}</div>'
    if e.type == "connector":
        return f'<div class="el" style="{style};border-top:1px solid #{e.line_hex or "999999"}"></div>'
    return ""


def export_html(pptx: Path | str, manifest: TemplateManifest, out: Path | str | None = None, title: Optional[str] = None, ir: Optional[DeckIR] = None) -> Path:
    pptx = Path(pptx)
    out = Path(out) if out else pptx.with_suffix(".html")
    ir = ir or build_deck_ir(pptx)
    pkg = PptxPackage.open(pptx)
    cache: dict[str, str] = {}
    default_font = manifest.tokens.typography.primary_family or "Play"
    slides_html = []
    slide_parts = list(pkg.slide_parts)
    for s in ir.slides:
        bg = s.background_hex or ("000000" if s.family.value == "dark" else "FFFFFF")
        parts = [f'<section class="slide" id="s{s.index}" style="background:#{bg}" data-index="{s.index}">']
        # the layout's and the master's pictures (logos, backdrops) are inherited by a slide in PPTX: drawn as the DECK has
        # them — the manifest describes the template as it was read, before a brand moved its logo into a corner
        slide_part = slide_parts[s.index - 1] if 0 < s.index <= len(slide_parts) else None
        layout_part = s.layout_part or (pkg.layout_of(slide_part) if slide_part else None)
        layers: list[str] = []
        try:
            master_part = pkg.master_of(layout_part) if layout_part else None
        except Exception:  # noqa: BLE001
            master_part = None
        hide_master = bool(layout_part) and pkg.xml(layout_part).get("showMasterSp") in ("0", "false")
        if master_part and not hide_master:
            layers.append(master_part)
        if layout_part:
            layers.append(layout_part)
        for layer in layers:
            for pic in _layer_pictures(pkg, layer, ir.slide_w, ir.slide_h):
                cls = _image_class(pkg, pic["image"], cache)
                if cls:
                    css = _crop_css(pic["crop"])
                    parts.append(f'<div class="el chrome pic{"" if css else " contain"} {cls}" style="left:{_pct(pic["x"])};top:{_pct(pic["y"])};width:{_pct(pic["w"])};height:{_pct(pic["h"])}{css}"></div>')
        facts = _slide_facts(pkg, slide_part, ir.slide_w)
        for e in sorted(s.elements, key=lambda e: e.z):
            parts.append(_element_html(e, s, ir, pkg, cache, manifest, default_font, facts))
        if s.notes:
            parts.append(f'<aside class="notes" hidden>{html.escape(s.notes)}</aside>')
        parts.append(f'<div class="num">{s.index} / {ir.n_slides}</div></section>')
        slides_html.append("".join(parts))
    pkg.close()
    image_css = "\n".join(f".{cls}{{background-image:url({uri})}}" for cls, uri in (cache.get("__uris__") or {}).items())  # type: ignore[union-attr]
    ratio = ir.slide_w / ir.slide_h
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title or pptx.stem)}</title>
<style>
{_font_face()}
:root{{color-scheme:light}}
body{{margin:0;background:#1e1e22;font-family:'{html.escape(default_font)}',Play,Arial,sans-serif;padding:24px 16px}}
.deck{{max-width:1280px;margin:0 auto}}
.slide{{position:relative;width:100%;aspect-ratio:{ratio:.5f};overflow:hidden;margin:0 auto 28px;box-shadow:0 10px 30px rgba(0,0,0,.35);border-radius:6px;container-type:inline-size}}
.el{{position:absolute;box-sizing:border-box;overflow:hidden}} .el.txt{{overflow:visible}}
.el.chrome{{pointer-events:none}}
.pic{{background-size:cover;background-position:center;background-repeat:no-repeat}} .pic.contain{{background-size:contain}}
{image_css}
.tx{{display:flex;flex-direction:column;height:100%;box-sizing:border-box;line-height:1.2;word-wrap:break-word}}
.tx p{{margin:0 0 0.25em 0}} .tx ul{{margin:0;padding-left:1.2em}} .tx li{{margin:0 0 0.25em 0}}
table{{border-collapse:collapse;width:100%;height:100%}} th,td{{padding:0.3em 0.6em;text-align:left;border-bottom:1px solid rgba(128,128,128,.35)}} th.n,td.n{{text-align:right}}
.num{{position:absolute;right:1cqw;bottom:0.6cqw;font-size:1.1cqw;opacity:.35}}
@media print{{body{{background:#fff;padding:0}} .slide{{box-shadow:none;border-radius:0;page-break-after:always;margin:0}} .num{{display:none}}}}
</style></head><body><div class="deck">
{"".join(slides_html)}
</div>
<script>
document.addEventListener('keydown',e=>{{const s=[...document.querySelectorAll('.slide')];const y=window.scrollY+10;let i=s.findIndex(el=>el.offsetTop>y);if(i<0)i=s.length;if(e.key==='ArrowRight'||e.key==='PageDown'){{(s[i]||s[s.length-1]).scrollIntoView({{behavior:'smooth'}});e.preventDefault();}}if(e.key==='ArrowLeft'||e.key==='PageUp'){{(s[Math.max(i-2,0)]).scrollIntoView({{behavior:'smooth'}});e.preventDefault();}}}});
</script></body></html>"""
    out.write_text(page, encoding="utf-8")
    return out
