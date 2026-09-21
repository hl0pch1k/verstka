"""generate_variants: one template + one brief/outline → decks for the requested strategies (+ audit, autofix, export)."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from verstka.analysis.manifest import analyze_template
from verstka.audit.autofix import autofix_loop
from verstka.audit.runner import run_audit
from verstka.export.html import export_html
from verstka.export.pdf import export_pdf
from verstka.ingest.render import RenderError, find_pdftoppm, find_soffice, render_slides
from verstka.ingest.workspace import TemplateWorkspace
from verstka.matching.matcher import match_outline
from verstka.pipeline.run_manifest import build_run_manifest, write_run_manifest
from verstka.planning.facts import extract_facts
from verstka.planning.outline import plan_outline, target_slide_count
from verstka.planning.strategies import STRATEGY_NAMES, Strategy, load_strategies
from verstka.providers.registry import ProviderRegistry
from verstka.rendering.renderer import RenderResult, render_deck
from verstka.schemas.audit import AuditReport
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
    audit: Optional[AuditReport] = None
    exports: dict[str, Path] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)


@dataclass
class GenerateResult:
    template_id: str
    manifest: TemplateManifest
    variants: list[VariantResult] = field(default_factory=list)
    seconds: float = 0.0


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


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
    audit: bool = True,
    autofix: bool = True,
    audit_models: bool = False,
    exports: Optional[list[str]] = None,
    progress: Optional[ProgressFn] = None,
) -> GenerateResult:
    if brief is None and outline is None:
        raise ValueError("either brief or outline is required")
    t0 = time.time()
    out_dir = Path(out_dir)
    strategies = strategies or list(STRATEGY_NAMES)
    all_strategies = load_strategies()
    exports = exports or []

    def report(msg: str, frac: float) -> None:
        log.info(msg)
        if progress:
            progress(msg, frac)

    ta = time.time()
    manifest = analyze_template(template, workspace_root=workspace_root, providers=providers, skills=skills, use_llm=use_llm, use_vlm=use_vlm, force=force_analyze, progress=lambda s, f: report(f"analyze: {s}", 0.15 * f))
    analyze_s = round(time.time() - ta, 2)
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
        timings: dict[str, float] = {"analyze": analyze_s}
        vdir = out_dir / name
        vdir.mkdir(parents=True, exist_ok=True)
        warnings = list(fact_warnings)
        base = 0.15 + 0.85 * i / n
        span = 0.85 / n
        tp = time.time()
        if outline is not None:
            v_outline = outline.model_copy(deep=True)
            v_outline.strategy = name
        else:
            target = target_slide_count(brief, strategy)
            v_outline, w = plan_outline(brief, manifest, strategy, facts, skills if use_llm else None, providers if use_llm else None, target=target)
            warnings.extend(w)
        timings["plan"] = round(time.time() - tp, 2)
        plan = match_outline(v_outline, manifest, strategy)
        report(f"{name}: planned {len(v_outline.slides)} slides, rendering", base + span * 0.2)
        tr = time.time()
        render = render_deck(v_outline, plan, manifest, ws, vdir / "deck.pptx", progress=lambda s, f: report(f"{name}: {s}", base + span * (0.2 + 0.3 * f)))
        timings["render"] = round(time.time() - tr, 2)
        warnings.extend(render.warnings)
        audit_report: Optional[AuditReport] = None
        if audit:
            tau = time.time()
            report(f"{name}: audit", base + span * 0.55)
            audit_report = run_audit(vdir / "deck.pptx", manifest, v_outline, ws, providers=providers if audit_models else None, skills=skills if audit_models else None, use_vlm=audit_models and use_vlm, use_llm=audit_models and use_llm, images_dir=vdir / "slides", strategy=name)
            if autofix and audit_report.summary.errors + audit_report.summary.warnings > 0:
                report(f"{name}: autofix ({audit_report.summary.errors} errors)", base + span * 0.7)
                audit_report, plan, v_outline, rr = autofix_loop(vdir / "deck.pptx", audit_report, v_outline, plan, manifest, ws, providers=providers, skills=skills, use_models=audit_models, images_dir=vdir / "slides")
                if rr is not None:
                    render = rr
            timings["audit"] = round(time.time() - tau, 2)
            (vdir / "audit_report.json").write_text(audit_report.model_dump_json(indent=2), encoding="utf-8")
        (vdir / "outline.json").write_text(v_outline.model_dump_json(indent=2), encoding="utf-8")
        (vdir / "layout_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        images: list[Path] = []
        if audit_report is not None and audit_report.slide_images:
            images = [Path(p) for _, p in sorted(audit_report.slide_images.items())]
        elif render_images and find_soffice() and find_pdftoppm():
            try:
                images = render_slides(vdir / "deck.pptx", vdir / "slides", dpi=110)
            except RenderError as e:
                warnings.append(f"render images failed: {e}")
        export_paths: dict[str, Path] = {"pptx": vdir / "deck.pptx"}
        te = time.time()
        for fmt in exports:
            try:
                if fmt == "pdf":
                    export_paths["pdf"] = export_pdf(vdir / "deck.pptx", vdir / "deck.pdf")
                elif fmt == "html":
                    export_paths["html"] = export_html(vdir / "deck.pptx", manifest, vdir / "deck.html", title=v_outline.title)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"export {fmt} failed: {str(e)[:160]}")
        timings["export"] = round(time.time() - te, 2)
        vr = VariantResult(strategy=name, out_dir=vdir, outline=v_outline, plan=plan, render=render, images=images, warnings=warnings, seconds=round(time.time() - ts, 2), audit=audit_report, exports=export_paths, timings=timings)
        timings["total"] = vr.seconds
        slides_info = [{"index": s.index, "outline_id": s.outline_id, "mode": s.mode, "pattern_id": s.pattern_id, "composition": s.composition, "warnings": s.warnings} for s in render.slides]
        rm = build_run_manifest(
            template_id=manifest.template_id,
            template_file=manifest.source_file,
            strategy=name,
            brief_hash=_sha(brief.text) if brief else None,
            outline_hash=_sha(v_outline.model_dump_json()),
            skills=skills,
            providers=providers,
            timings=timings,
            applied_fixes=audit_report.applied_fixes if audit_report else [],
            audit_summary=audit_report.summary.model_dump() if audit_report else {},
            slides=slides_info,
            extra={"warnings": warnings, "exports": {k: str(v) for k, v in export_paths.items()}},
        )
        write_run_manifest(vdir / "run_manifest.json", rm)
        result.variants.append(vr)
        report(f"{name}: done in {vr.seconds}s", base + span)
    result.seconds = round(time.time() - t0, 2)
    return result
