"""Thumbnails and an HTML gallery of patterns for humans (and the web UI)."""

from __future__ import annotations

import html
from collections import Counter
from pathlib import Path

from verstka.ingest.workspace import TemplateWorkspace
from verstka.schemas.template import TemplateManifest


def write_thumbnails(images: dict[int, Path], out_dir: Path, width: int = 480) -> dict[int, Path]:
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    out: dict[int, Path] = {}
    for i, src in images.items():
        dst = out_dir / f"slide-{i:03d}.jpg"
        if not dst.exists():
            with Image.open(src) as im:
                im = im.convert("RGB")
                if im.width > width:
                    im = im.resize((width, int(im.height * width / im.width)))
                im.save(dst, format="JPEG", quality=82)
        out[i] = dst
    return out


def write_gallery(manifest: TemplateManifest, ws: TemplateWorkspace) -> Path:
    t = manifest.tokens
    swatches = "".join(
        f'<div class="sw"><div class="chip" style="background:#{c.hex}"></div><div>#{c.hex}<br><small>{html.escape(c.role or "")} · {c.weight:g}</small></div></div>'
        for c in t.colors[:14]
    )
    fonts = ", ".join(f"{html.escape(f.family)} ({f.weight:.0%})" for f in t.typography.families[:4])
    scale = ", ".join(f"{s.role} {s.size_pt:g}" for s in t.typography.scale)
    kinds = Counter(p.kind.value for p in manifest.patterns)
    kinds_html = " ".join(f'<span class="tag">{k}: {v}</span>' for k, v in kinds.most_common())
    cards = []
    for p in manifest.patterns:
        roles = Counter(s.role.value for s in p.slots)
        roles_html = ", ".join(f"{r}×{n}" for r, n in roles.most_common())
        groups_html = "; ".join(f"{len(g.member_shape_ids)} cells {g.axis} (max {g.max_n})" for g in p.repeat_groups)
        tr = p.classification
        votes = ""
        if tr:
            votes = f"heur {tr.heuristic.kind.value} {tr.heuristic.confidence:.2f}"
            if tr.llm:
                votes += f" · llm {tr.llm.kind.value} {tr.llm.confidence:.2f}"
            if tr.vlm:
                votes += f" · vlm {tr.vlm.kind.value} {tr.vlm.confidence:.2f}"
            votes += f" · agreement {tr.agreement:.2f}"
        img = f'<img src="{html.escape(p.thumbnail)}" alt="">' if p.thumbnail else '<div class="noimg">no render</div>'
        purpose = html.escape(tr.purpose) if tr and tr.purpose else ""
        cards.append(
            f'<div class="card"><div class="head"><b>{p.id}</b> · slide {p.source_slide} · <span class="kind">{p.kind.value}</span> · {p.family.value} · q={p.quality:g}</div>'
            f"{img}<div class=\"meta\">{html.escape(roles_html)}<br>{html.escape(groups_html)}<br><small>{html.escape(votes)}</small><br><i>{purpose}</i></div></div>"
        )
    rules = "".join(f"<li>{html.escape(r.text)} <small>({r.source}, {r.confidence:g})</small></li>" for r in manifest.style_rules)
    warnings = "".join(f"<li>{html.escape(w)}</li>" for w in manifest.warnings)
    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Verstka gallery — {html.escape(manifest.source_file)}</title>
<style>body{{font:14px/1.4 -apple-system,Segoe UI,Arial,sans-serif;margin:24px;color:#222;background:#fafafa}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}}
.card{{background:#fff;border:1px solid #e3e3e3;border-radius:10px;overflow:hidden}} .card img{{width:100%;display:block}}
.head{{padding:8px 10px;background:#f2f4f7;font-size:13px}} .meta{{padding:8px 10px;font-size:12px;color:#444}}
.kind{{background:#0077ff;color:#fff;padding:1px 6px;border-radius:6px}} .tag{{display:inline-block;background:#eef;padding:2px 8px;border-radius:8px;margin:2px}}
.sw{{display:inline-flex;align-items:center;gap:8px;margin:4px 12px 4px 0;font-size:12px}} .chip{{width:28px;height:28px;border-radius:6px;border:1px solid #ccc}}
.noimg{{height:180px;display:flex;align-items:center;justify-content:center;color:#999}} h2{{margin-top:28px}}</style></head><body>
<h1>{html.escape(manifest.source_file)}</h1>
<p>{manifest.n_slides} slides · {manifest.slide_size.w / 914400:.2f}×{manifest.slide_size.h / 914400:.2f} in · {len(manifest.patterns)} patterns · {len(manifest.assets)} assets · embedded fonts: {html.escape(", ".join(manifest.embedded_fonts) or "none")}</p>
<h2>Tokens</h2><div>{swatches}</div><p><b>Fonts:</b> {fonts}<br><b>Scale:</b> {scale}<br><b>Safe area:</b> x={t.spacing.safe_area.x:.2f} y={t.spacing.safe_area.y:.2f} w={t.spacing.safe_area.w:.2f} h={t.spacing.safe_area.h:.2f} · columns {t.spacing.columns} · gutter {t.spacing.gutter}<br>
<b>Chrome:</b> {len(t.chrome)} elements · <b>Shapes:</b> rounded {t.shapes.corner_radius_share:.0%}, lines {t.shapes.line_share:.0%}, shadows {t.shapes.shadow_share:.0%}</p>
<h2>Patterns</h2><p>{kinds_html}</p><div class="grid">{"".join(cards)}</div>
<h2>Style rules</h2><ul>{rules}</ul>
<h2>Warnings</h2><ul>{warnings or "<li>none</li>"}</ul>
</body></html>"""
    ws.gallery_path.write_text(page, encoding="utf-8")
    return ws.gallery_path
