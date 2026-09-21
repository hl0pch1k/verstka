"""Single-file HTML export built from DeckIR: real markup, embedded fonts and images, SVG charts, HTML tables."""

from __future__ import annotations

import base64
import html
from pathlib import Path
from typing import Optional

from verstka.audit.ir import build_deck_ir
from verstka.export.svg_charts import chart_svg
from verstka.ingest.package import PptxPackage
from verstka.rendering.fonts import FONT_DIR
from verstka.schemas.common import EMU_PER_PT, contrast_ratio
from verstka.schemas.deck_ir import DeckIR, IRElement, IRSlide
from verstka.schemas.template import TemplateManifest

_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "svg": "image/svg+xml", "webp": "image/webp", "bmp": "image/bmp", "emf": "image/emf", "wmf": "image/wmf"}


def _data_uri(pkg: PptxPackage, part: Optional[str], cache: dict[str, str]) -> Optional[str]:
    if not part or not pkg.exists(part):
        return None
    if part in cache:
        return cache[part]
    ext = part.rsplit(".", 1)[-1].lower()
    mime = _MIME.get(ext)
    if mime is None or ext in ("emf", "wmf"):
        cache[part] = ""
        return None
    uri = f"data:{mime};base64," + base64.b64encode(pkg.read(part)).decode("ascii")
    cache[part] = uri
    return uri


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


def _text_html(e: IRElement, slide_w: int, default_color: str, default_font: str) -> str:
    align = {"ctr": "center", "r": "right", "just": "justify"}.get(e.paragraphs[0].align or "", "left") if e.paragraphs else "left"
    vpos = {"ctr": "center", "b": "flex-end"}.get(e.anchor or "t", "flex-start")
    inner = []
    in_list = False
    for p in e.paragraphs:
        runs = "".join(
            f'<span style="font-size:{_size_css(r.size_pt or 14, slide_w)};color:#{r.color_hex or default_color};font-weight:{700 if r.bold else 400};font-style:{"italic" if r.italic else "normal"};font-family:\'{html.escape(r.font or default_font)}\',Play,Arial,sans-serif">{html.escape(r.text)}</span>'
            for r in p.runs
            if r.text
        ) or "&nbsp;"
        if p.bullet:
            if not in_list:
                inner.append("<ul>")
                in_list = True
            inner.append(f'<li style="margin-left:{p.level * 1.2}em">{runs}</li>')
        else:
            if in_list:
                inner.append("</ul>")
                in_list = False
            inner.append(f'<p style="text-align:{align}">{runs}</p>')
    if in_list:
        inner.append("</ul>")
    return f'<div class="tx" style="justify-content:{vpos}">{"".join(inner)}</div>'


def _shape_css(e: IRElement, slide_w: int, slide_h: int) -> str:
    css = []
    if e.fill_hex:
        css.append(f"background:#{e.fill_hex}")
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


def _element_html(e: IRElement, slide: IRSlide, ir: DeckIR, pkg: PptxPackage, cache: dict, manifest: TemplateManifest, default_font: str) -> str:
    f = e.bbox_frac
    style = f"left:{_pct(f.x)};top:{_pct(f.y)};width:{_pct(f.w)};height:{_pct(f.h)};z-index:{e.z}"
    bg = slide.background_hex or ("000000" if slide.family.value == "dark" else "FFFFFF")
    text_default = manifest.tokens.color_for("text.primary") or "000000"
    if contrast_ratio(text_default, bg) < 2.5:
        text_default = "FFFFFF" if slide.family.value == "dark" else "000000"
    if e.type == "picture":
        uri = _data_uri(pkg, e.image_part, cache)
        if not uri:
            return ""
        return f'<div class="el" style="{style}"><img src="{uri}" alt="" style="width:100%;height:100%;object-fit:cover"></div>'
    if e.type == "chart" and e.chart:
        colors = manifest.components.chart_style.series_colors or manifest.tokens.accents()
        svg = chart_svg(e.chart, e.bbox.w / EMU_PER_PT, e.bbox.h / EMU_PER_PT, colors, text_hex=text_default, font=f"'{default_font}', Play, Arial, sans-serif", font_px=max(manifest.components.chart_style.font_size_pt, 9))
        return f'<div class="el" style="{style}">{svg}</div>'
    if e.type == "table" and e.table and e.table.rows:
        ts = manifest.components.table_style
        rows = e.table.rows
        head = "".join(f'<th style="background:#{e.table.header_fill_hex or ts.header_fill_hex or "0077FF"};color:#{ts.header_text_hex or "FFFFFF"}">{html.escape(c)}</th>' for c in rows[0])
        body = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
        return f'<div class="el" style="{style}"><table style="font-size:{_size_css(ts.font_size_pt, ir.slide_w)};color:#{ts.body_text_hex or text_default}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
    if e.type in ("text", "shape"):
        box = _shape_css(e, ir.slide_w, ir.slide_h)
        inner = _text_html(e, ir.slide_w, text_default, default_font) if e.has_text else ""
        return f'<div class="el" style="{style};{box}">{inner}</div>'
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
    # layout/master chrome (logos, footers) is inherited in PPTX; draw it from the manifest's chrome inventory
    chrome_by_layout: dict[str, list] = {}
    for c in manifest.tokens.chrome:
        if c.source.startswith("layout:") or c.source.startswith("master:"):
            chrome_by_layout.setdefault(c.source.split(":", 1)[1], []).append(c)
    slides_html = []
    for s in ir.slides:
        bg = s.background_hex or ("000000" if s.family.value == "dark" else "FFFFFF")
        parts = [f'<section class="slide" id="s{s.index}" style="background:#{bg}" data-index="{s.index}">']
        layout_chrome = chrome_by_layout.get(s.layout_part or "", [])
        master_part = None
        try:
            master_part = pkg.master_of(s.layout_part) if s.layout_part else None
        except Exception:  # noqa: BLE001
            master_part = None
        if master_part:
            layout_chrome = layout_chrome + chrome_by_layout.get(master_part, [])
        for c in layout_chrome:
            if c.kind == "pic" and c.image_part:
                uri = _data_uri(pkg, c.image_part, cache)
                if uri:
                    parts.append(f'<div class="el chrome" style="left:{_pct(c.bbox.x)};top:{_pct(c.bbox.y)};width:{_pct(c.bbox.w)};height:{_pct(c.bbox.h)}"><img src="{uri}" alt="" style="width:100%;height:100%;object-fit:contain"></div>')
        for e in sorted(s.elements, key=lambda e: e.z):
            parts.append(_element_html(e, s, ir, pkg, cache, manifest, default_font))
        if s.notes:
            parts.append(f'<aside class="notes" hidden>{html.escape(s.notes)}</aside>')
        parts.append(f'<div class="num">{s.index} / {ir.n_slides}</div></section>')
        slides_html.append("".join(parts))
    pkg.close()
    ratio = ir.slide_w / ir.slide_h
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title or pptx.stem)}</title>
<style>
{_font_face()}
:root{{color-scheme:light}}
body{{margin:0;background:#1e1e22;font-family:'{html.escape(default_font)}',Play,Arial,sans-serif;padding:24px 16px}}
.deck{{max-width:1280px;margin:0 auto}}
.slide{{position:relative;width:100%;aspect-ratio:{ratio:.5f};overflow:hidden;margin:0 auto 28px;box-shadow:0 10px 30px rgba(0,0,0,.35);border-radius:6px;container-type:inline-size}}
.el{{position:absolute;box-sizing:border-box;overflow:hidden}}
.el.chrome{{pointer-events:none}}
.tx{{display:flex;flex-direction:column;height:100%;padding:0.35cqw 0.6cqw;box-sizing:border-box;line-height:1.2;word-wrap:break-word}}
.tx p{{margin:0 0 0.25em 0}} .tx ul{{margin:0;padding-left:1.2em}} .tx li{{margin:0 0 0.25em 0}}
table{{border-collapse:collapse;width:100%;height:100%}} th,td{{padding:0.3em 0.6em;text-align:left;border-bottom:1px solid rgba(128,128,128,.35)}} td:not(:first-child){{text-align:right}}
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
