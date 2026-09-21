"""generate_variants: one template + one brief/outline → decks for the requested strategies."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from verstka.analysis.manifest import analyze_template
from verstka.ingest.render import RenderError, find_pdftoppm, find_soffice, render_slides
from verstka.ingest.workspace import TemplateWorkspace
from verstka.matching.matcher import match_outline
from verstka.planning.facts import extract_facts
from verstka.planning.outline import plan_outline, target_slide_count
from verstka.planning.strategies import STRATEGY_NAMES, Strategy, load_strategies
from verstka.providers.registry import ProviderRegistry
from verstka.rendering.renderer import RenderResult, render_deck
from verstka.schemas.layout import LayoutPlan
from verstka.schemas.outline import Brief, DeckOutline, FactsExtraction
from verstka.schemas.template import TemplateManifest
from verstka.skills_registry.registry import SkillsRegistry

log = logging.getLogger(__name__)
ProgressFn = Callable[[str, float], None]


@dataclass
class VariantResult:
    strategy: str
    out_dir: Path
    outline: DeckOutline
    plan: LayoutPlan
    render: RenderResult
    images: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0


@dataclass
class GenerateResult:
    template_id: str
    manifest: TemplateManifest
    variants: list[VariantResult] = field(default_factory=list)
    seconds: float = 0.0


def generate_variants(
    template: Path | str,
    *,
    brief: Optional[Brief] = None,
    outline: Optional[DeckOutline] = None,
    strategies: Optional[list[str]] = None,
    out_dir: Path | str = "out",
    workspace_root: Optional[Path | str] = None,
    providers: Optional[ProviderRegistry] = None,
    skills: Optional[SkillsRegistry] = None,
    use_llm: bool = True,
    use_vlm: bool = True,
    render_images: bool = False,
    force_analyze: bool = False,
    progress: Optional[ProgressFn] = None,
) -> GenerateResult:
    if brief is None and outline is None:
        raise ValueError("either brief or outline is required")
    t0 = time.time()
    out_dir = Path(out_dir)
    strategies = strategies or list(STRATEGY_NAMES)
    all_strategies = load_strategies()

    def report(msg: str, frac: float) -> None:
        log.info(msg)
        if progress:
            progress(msg, frac)

    manifest = analyze_template(template, workspace_root=workspace_root, providers=providers, skills=skills, use_llm=use_llm, use_vlm=use_vlm, force=force_analyze, progress=lambda s, f: report(f"analyze: {s}", 0.2 * f))
    ws = TemplateWorkspace.open(manifest.template_id, workspace_root)
    result = GenerateResult(template_id=manifest.template_id, manifest=manifest)
    facts: Optional[FactsExtraction] = None
    fact_warnings: list[str] = []
    if brief is not None and outline is None:
        facts, fact_warnings = extract_facts(brief, skills if use_llm else None, providers if use_llm else None)
    n = len(strategies)
    for i, name in enumerate(strategies):
        strategy: Strategy = all_strategies[name]
        ts = time.time()
        vdir = out_dir / name
        vdir.mkdir(parents=True, exist_ok=True)
        warnings = list(fact_warnings)
        if outline is not None:
            v_outline = outline.model_copy(deep=True)
            v_outline.strategy = name
        else:
            target = target_slide_count(brief, strategy)
            v_outline, w = plan_outline(brief, manifest, strategy, facts, skills if use_llm else None, providers if use_llm else None, target=target)
            warnings.extend(w)
        (vdir / "outline.json").write_text(v_outline.model_dump_json(indent=2), encoding="utf-8")
        plan = match_outline(v_outline, manifest, strategy)
        (vdir / "layout_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        report(f"{name}: planned {len(v_outline.slides)} slides, rendering", 0.2 + 0.8 * (i + 0.3) / n)
        render = render_deck(v_outline, plan, manifest, ws, vdir / "deck.pptx", progress=lambda s, f, _i=i: report(f"{name}: {s}", 0.2 + 0.8 * (_i + 0.3 + 0.6 * f) / n))
        warnings.extend(render.warnings)
        images: list[Path] = []
        if render_images and find_soffice() and find_pdftoppm():
            try:
                images = render_slides(render.pptx_path, vdir / "slides", dpi=110)
            except RenderError as e:
                warnings.append(f"render images failed: {e}")
        vr = VariantResult(strategy=name, out_dir=vdir, outline=v_outline, plan=plan, render=render, images=images, warnings=warnings, seconds=round(time.time() - ts, 2))
        (vdir / "render_report.json").write_text(
            json.dumps(
                {
                    "strategy": name,
                    "template_id": manifest.template_id,
                    "slides": [{"index": s.index, "outline_id": s.outline_id, "mode": s.mode, "pattern_id": s.pattern_id, "composition": s.composition, "warnings": s.warnings} for s in render.slides],
                    "warnings": warnings,
                    "seconds": vr.seconds,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        result.variants.append(vr)
        report(f"{name}: done in {vr.seconds}s", 0.2 + 0.8 * (i + 1) / n)
    result.seconds = round(time.time() - t0, 2)
    return result
