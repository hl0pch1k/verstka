"""analyze_template: the full template analysis pipeline → TemplateManifest."""

from __future__ import annotations

import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

import yaml

from verstka.analysis.assets import extract_assets, tag_assets_with_vlm
from verstka.analysis.chrome import chrome_ids as _chrome_ids
from verstka.analysis.chrome import detect_chrome, inherited_chrome, visual_chrome
from verstka.analysis.classify import classify_slide
from verstka.analysis.colors import ColorSample, assign_color_roles, cluster_colors, collect_color_samples
from verstka.analysis.components import derive_components
from verstka.analysis.gallery import write_gallery, write_thumbnails
from verstka.analysis.groups import detect_repeat_groups
from verstka.analysis.patterns import build_pattern, dedupe_patterns
from verstka.analysis.rules import harvest_rules, with_fresh_derived_rules
from verstka.analysis.shapes import ShapeInfo, SlideContext, extract_shapes, slide_background, slide_family
from verstka.analysis.spacing import compute_spacing
from verstka.analysis.typography import build_type_scale
from verstka.ingest.package import PptxPackage
from verstka.ingest.render import RenderError, find_pdftoppm, find_soffice, render_slides
from verstka.ingest.workspace import TemplateWorkspace
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.common import Family, ShapeKind, contrast_ratio
from verstka.schemas.template import BackgroundFamily, ShapeStyleStats, SlideSize, TemplateManifest, Tokens
from verstka.skills_registry.registry import SkillsRegistry

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None]


def load_analysis_config(path: Optional[Path] = None) -> dict:
    path = path or Path(__file__).resolve().parents[2] / "configs" / "analysis.yaml"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _shape_style_stats(shapes_by_slide: dict[int, list[ShapeInfo]], chrome_by_slide: dict[int, set[str]]) -> ShapeStyleStats:
    rects = 0
    rounded = 0
    radii: list[float] = []
    lined = 0
    line_ws: list[float] = []
    shadows = 0
    visual = 0
    fills: Counter = Counter()
    for idx, shapes in shapes_by_slide.items():
        chrome = chrome_by_slide.get(idx, set())
        for s in shapes:
            if s.id in chrome or s.kind != ShapeKind.sp or not (s.fill_hex or s.line_hex):
                continue
            visual += 1
            if s.geometry in ("rect", "roundRect", "round2SameRect", "snipRoundRect"):
                rects += 1
                if s.geometry != "rect":
                    rounded += 1
                    if s.corner_radius is not None:
                        radii.append(s.corner_radius)
            if s.line_hex:
                lined += 1
                if s.line_w_emu:
                    line_ws.append(s.line_w_emu / 12700.0)
            if s.has_shadow:
                shadows += 1
            if s.fill_hex and s.has_text:
                fills[s.fill_hex] += 1
    stats = ShapeStyleStats(
        corner_radius_share=round(rounded / rects, 3) if rects else 0.0,
        typical_radius=round(sorted(radii)[len(radii) // 2], 4) if radii else None,
        line_share=round(lined / visual, 3) if visual else 0.0,
        typical_line_w_pt=round(sorted(line_ws)[len(line_ws) // 2], 2) if line_ws else None,
        shadow_share=round(shadows / visual, 3) if visual else 0.0,
        card_fill_hex=fills.most_common(1)[0][0] if fills else None,
    )
    return stats


def template_summary_text(n_slides: int, slide_w: int, slide_h: int, tokens: Tokens, families: Counter) -> str:
    fonts = ", ".join(f.family for f in tokens.typography.families[:2]) or "unknown"
    accents = ", ".join("#" + a for a in tokens.accents()[:3]) or "none"
    fam = ", ".join(f"{k}: {v}" for k, v in families.items())
    return f"{n_slides} slides, {slide_w / 914400:.2f}x{slide_h / 914400:.2f} in; fonts {fonts}; accents {accents}; slide families {fam}"


def _draws(s: ShapeInfo) -> bool:
    return s.kind == ShapeKind.pic or s.is_visual_shape or s.has_text


def _drawn_box(s: ShapeInfo, slide_w: int, slide_h: int):
    """Where a shape actually puts ink: a wide text box only as far as its longest line reaches."""
    f = s.bbox.to_frac(slide_w, slide_h)
    if s.kind == ShapeKind.pic or s.is_visual_shape or not s.has_text:
        return f
    size = (s.text.dominant_size_pt or 18.0) if s.text else 18.0
    longest = max((len(line) for line in s.plain_text.splitlines()), default=0)
    width = min(f.w, longest * size * 0.6 * 12700 / slide_w)
    return f.model_copy(update={"w": width})


def text_color_on(under_hex: Optional[str], tokens: Tokens) -> Optional[str]:
    """The template's own text colour that reads best on `under_hex` (primary text first, then the backgrounds)."""
    if not under_hex:
        return tokens.color_for("text.primary")
    candidates = [tokens.color_for(r) for r in ("text.primary", "text.secondary", "background.dark", "background.light")]
    candidates = [c for c in candidates if c] + ["000000", "FFFFFF"]
    for c in candidates:
        if contrast_ratio(c, under_hex) >= 4.5:
            return c
    return max(candidates, key=lambda c: contrast_ratio(c, under_hex))


def analyze_template(
    pptx: Path | str,
    *,
    workspace_root: Optional[Path | str] = None,
    providers: Optional[ProviderRegistry] = None,
    skills: Optional[SkillsRegistry] = None,
    use_llm: bool = True,
    use_vlm: bool = True,
    tag_assets: bool = False,
    render: bool = True,
    force: bool = False,
    max_workers: int = 4,
    config: Optional[dict] = None,
    progress: Optional[ProgressFn] = None,
) -> TemplateManifest:
    cfg = config or load_analysis_config()
    t0 = time.time()

    def report(stage: str, frac: float) -> None:
        log.info("[%5.1fs] %s", time.time() - t0, stage)
        if progress:
            progress(stage, frac)

    ws = TemplateWorkspace.create(pptx, workspace_root)
    if ws.is_analyzed and not force:
        cached = TemplateManifest.model_validate_json(ws.manifest_path.read_text(encoding="utf-8"))
        if cached.analysis_version == TemplateManifest.model_fields["analysis_version"].default:
            report("loaded cached manifest", 1.0)
            return with_fresh_derived_rules(cached)
        log.info("cached manifest has analysis_version %s, re-analyzing", cached.analysis_version)

    warnings: list[str] = []
    pkg = PptxPackage.open(ws.source)
    slide_w, slide_h = pkg.slide_size
    slide_parts = pkg.slide_parts
    n_slides = len(slide_parts)
    report(f"opened package: {n_slides} slides", 0.02)

    # 1. render
    images: dict[int, Path] = {}
    if render and find_soffice() and find_pdftoppm():
        try:
            paths = render_slides(ws.source, ws.slides_dir, dpi=int(cfg.get("render", {}).get("dpi", 110)))
            images = {i + 1: p for i, p in enumerate(paths)}
        except RenderError as e:
            warnings.append(f"render failed: {e}")
    elif render:
        warnings.append("LibreOffice/poppler not found: slides not rendered, VLM checks disabled")
    if not images:
        use_vlm = False
    report("rendered slides", 0.2)

    # 2. shapes per slide
    shapes_by_slide: dict[int, list[ShapeInfo]] = {}
    family_by_slide: dict[int, Family] = {}
    bg_by_slide: dict[int, Optional[str]] = {}
    image_bg: set[int] = set()
    layout_by_slide: dict[int, Optional[str]] = {}
    slide_texts: list[str] = []
    for i, part in enumerate(slide_parts, 1):
        try:
            ctx = SlideContext(pkg, part)
            shapes = extract_shapes(pkg, part, ctx)
            fam, bg = slide_family(pkg, part, ctx, shapes, str(images[i]) if i in images else None)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"slide {i}: extraction failed: {str(e)[:200]}")
            log.exception("slide %d extraction failed", i)
            continue
        shapes_by_slide[i] = shapes
        family_by_slide[i] = fam
        bg_by_slide[i] = bg
        if bg and slide_background(pkg, part, ctx)[1] == "image":
            image_bg.add(i)  # a median colour of a picture ground, not a solid fill
        layout_by_slide[i] = ctx.layout_part
        slide_texts.append("\n".join(s.plain_text for s in shapes if s.has_text))
    report("extracted shapes", 0.3)

    # 3. chrome
    chrome_cfg = cfg.get("chrome", {})
    chrome = detect_chrome(shapes_by_slide, slide_w, slide_h, min_share=float(chrome_cfg.get("min_share", 0.4)), min_slides=int(chrome_cfg.get("min_slides", 3)))
    chrome_by_slide = {i: _chrome_ids(shapes, chrome, slide_w, slide_h) for i, shapes in shapes_by_slide.items()}
    # chrome inherited from layouts and masters (logos, footers) — recorded for audits and the synth renderer
    layout_users: dict[str, list[int]] = {}
    for i, lp in layout_by_slide.items():
        if lp:
            layout_users.setdefault(lp, []).append(i)
    layout_shapes: dict[str, list[ShapeInfo]] = {}
    master_users: dict[str, list[int]] = {}
    master_shapes: dict[str, list[ShapeInfo]] = {}
    for lp, users in layout_users.items():
        try:
            layout_shapes[lp] = extract_shapes(pkg, lp, SlideContext(pkg, lp))
            mp = pkg.master_of(lp)
            if mp:
                master_users.setdefault(mp, []).extend(users)
                if mp not in master_shapes:
                    master_shapes[mp] = extract_shapes(pkg, mp, SlideContext(pkg, mp))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"layout {lp}: chrome extraction failed: {str(e)[:120]}")
    chrome.extend(inherited_chrome(layout_shapes, layout_users, n_slides, slide_w, slide_h, "layout"))
    chrome.extend(inherited_chrome(master_shapes, master_users, n_slides, slide_w, slide_h, "master"))
    if images:
        # logos baked into background pictures exist only in the renders
        known = [c.bbox for c in chrome]
        for vc in visual_chrome([str(p) for _, p in sorted(images.items())]):
            if any(vc.bbox.intersection(k) > 0.5 * vc.bbox.area for k in known if k.area > 0):
                continue
            # edges drawn by real shapes (title pills, headings standing at the same place) are not baked chrome
            drawn = sum(1 for shapes in shapes_by_slide.values() if any(_drawn_box(s, slide_w, slide_h).intersection(vc.bbox) >= 0.4 * vc.bbox.area for s in shapes if _draws(s)))
            if drawn >= 0.3 * max(len(shapes_by_slide), 1):
                continue
            chrome.append(vc)
    chrome_image_parts = {c.image_part for c in chrome if c.image_part}

    # 4. assets
    assets, asset_id_by_part = extract_assets(pkg, shapes_by_slide, ws.assets_dir, chrome_image_parts, slide_w, slide_h)
    image_kinds = {a.media_part: a.kind for a in assets if a.media_part}
    for part, aid in asset_id_by_part.items():
        if part not in image_kinds:
            image_kinds[part] = next((a.kind for a in assets if a.id == aid), "other")
    report(f"extracted {len(assets)} assets", 0.38)

    # 5. typography, colours
    typography = build_type_scale(shapes_by_slide, chrome_by_slide)
    families = Counter(f.value for f in family_by_slide.values())
    primary_family = Family.dark if families.get("dark", 0) > families.get("light", 0) else Family.light
    samples = []
    for i, shapes in shapes_by_slide.items():
        # a picture ground is represented by its median colour: an approximation, so it only whispers in the palette
        solid_bg = bg_by_slide.get(i) if i not in image_bg else None
        samples.extend(collect_color_samples(shapes, slide_w, slide_h, bg_hex=solid_bg, chrome_ids=chrome_by_slide[i]))
        if i in image_bg and bg_by_slide.get(i):
            samples.append(ColorSample(bg_by_slide[i].upper(), "background", 0.5))
    # the brand also lives on masters and layouts (rules, bars, logos) and in the theme: light votes, so that a
    # template whose slides are all black-on-white still has its accent (instead of a VK blue default)
    art = [s for shapes in list(layout_shapes.values()) + list(master_shapes.values()) for s in shapes if not s.is_placeholder]
    for smp in collect_color_samples(art, slide_w, slide_h):
        if smp.context != "background":
            samples.append(ColorSample(smp.hex, smp.context, smp.weight * 0.5))
    try:
        theme = SlideContext(pkg, slide_parts[0]).resolver if slide_parts else None
        for k, name in enumerate(("accent1", "accent2")):
            hx = theme.scheme_hex(name) if theme is not None else None
            if hx:
                samples.append(ColorSample(hx.upper(), "fill", 0.2 - 0.05 * k))
    except Exception:  # noqa: BLE001
        pass
    colors = assign_color_roles(cluster_colors(samples, float(cfg.get("colors", {}).get("delta_e_tolerance", 1.8))), primary_family)

    # 6. spacing (preliminary) and groups
    spacing = compute_spacing(shapes_by_slide, chrome_by_slide, slide_w, slide_h, min_column_share=float(cfg.get("spacing", {}).get("min_column_share", 0.25)))
    groups_by_slide = {}
    gaps: list[float] = []
    for i, shapes in shapes_by_slide.items():
        groups = detect_repeat_groups(shapes, slide_w, slide_h, chrome_ids=chrome_by_slide[i], safe_area=spacing.safe_area, size_tol=float(cfg.get("groups", {}).get("size_tolerance", 0.06)))
        groups_by_slide[i] = groups
        gaps.extend(g.gap for g in groups if g.axis == "row" and g.gap > 0)
    spacing = compute_spacing(shapes_by_slide, chrome_by_slide, slide_w, slide_h, gaps=gaps, min_column_share=float(cfg.get("spacing", {}).get("min_column_share", 0.25)))
    shape_stats = _shape_style_stats(shapes_by_slide, chrome_by_slide)
    backgrounds: dict[tuple, BackgroundFamily] = {}
    for i, fam in family_by_slide.items():
        solid = bg_by_slide.get(i) and i not in image_bg
        key = (fam.value, bg_by_slide.get(i) if solid else "image")
        bf = backgrounds.setdefault(key, BackgroundFamily(family=fam, fill_kind="solid" if solid else "image", hex=bg_by_slide.get(i)))
        bf.slides.append(i)
    tokens = Tokens(colors=colors, typography=typography, spacing=spacing, shapes=shape_stats, chrome=chrome, backgrounds=sorted(backgrounds.values(), key=lambda b: -len(b.slides)))
    report("built tokens", 0.45)

    # 7. classification (parallel when using models)
    summary = template_summary_text(n_slides, slide_w, slide_h, tokens, families)
    cls_cfg = cfg.get("classification", {})
    weights = (float(cls_cfg.get("heuristic_weight", 1.0)), float(cls_cfg.get("llm_weight", 1.5)), float(cls_cfg.get("vlm_weight", 1.0)))
    override = float(cls_cfg.get("llm_role_override_confidence", 0.7))

    def _classify(i: int):
        shapes = shapes_by_slide[i]
        return i, classify_slide(
            shapes,
            groups_by_slide[i],
            chrome_by_slide[i],
            typography,
            i,
            n_slides,
            slide_w,
            slide_h,
            image_path=images.get(i),
            image_kinds=image_kinds,
            skills=skills,
            providers=providers,
            use_llm=use_llm,
            use_vlm=use_vlm,
            template_summary=summary,
            weights=weights,
            role_override_confidence=override,
        )

    results = {}
    indices = sorted(shapes_by_slide)
    workers = max_workers if (use_llm or use_vlm) and providers is not None else 1
    if workers > 1:
        with ThreadPoolExecutor(max_workers=min(workers, providers.limits.max_concurrency if providers else workers)) as ex:
            for i, res in ex.map(_classify, indices):
                results[i] = res
    else:
        for i in indices:
            results[i] = _classify(i)[1]
    report("classified slides", 0.8)

    # 8. thumbnails and patterns
    thumbs = write_thumbnails(images, ws.thumbs_dir, width=int(cfg.get("render", {}).get("thumb_width", 480))) if images else {}
    patterns = []
    for i in indices:
        trace, roles, w = results[i]
        warnings.extend(w)
        thumb = str(thumbs[i].relative_to(ws.dir)) if i in thumbs else None
        patterns.append(
            build_pattern(
                f"p{i}",
                i,
                shapes_by_slide[i],
                roles,
                groups_by_slide[i],
                trace,
                family_by_slide[i],
                slide_w,
                slide_h,
                thumbnail=thumb,
                layout_part=layout_by_slide.get(i),
                asset_ids=asset_id_by_part,
                line_spacing=typography.line_spacing,
                body_size=typography.size_for("body", 14.0),
                text_on=lambda fill, i=i: text_color_on(fill or bg_by_slide.get(i) or tokens.color_for("background.dark" if family_by_slide[i] == Family.dark else "background.light"), tokens),
            )
        )
    patterns = dedupe_patterns(patterns)
    report(f"assembled {len(patterns)} patterns", 0.86)

    # 9. components, rules, optional asset tagging
    components = derive_components(patterns, shapes_by_slide, tokens)
    rules, w = harvest_rules(slide_texts, tokens, skills, providers, use_llm=use_llm)
    warnings.extend(w)
    if tag_assets and use_vlm and skills is not None and providers is not None:
        warnings.extend(tag_assets_with_vlm(assets, ws.dir, skills, providers))
    report("derived components and rules", 0.95)

    manifest = TemplateManifest(
        template_id=ws.template_id,
        source_file=ws.original_name,
        slide_size=SlideSize(w=slide_w, h=slide_h),
        tokens=tokens,
        patterns=patterns,
        components=components,
        assets=assets,
        style_rules=rules,
        warnings=warnings,
        n_slides=n_slides,
        embedded_fonts=pkg.embedded_fonts,
    )
    ws.manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    try:
        write_gallery(manifest, ws)
    except Exception as e:  # noqa: BLE001
        log.warning("gallery failed: %s", e)
    pkg.close()
    report("done", 1.0)
    return manifest
