"""generate_variants: one template + one brief/outline → decks for the requested strategies (+ audit, autofix, export)."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from verstka.analysis.manifest import analyze_template
from verstka.audit.autofix import autofix_loop
from verstka.audit.runner import run_audit
from verstka.export.html import export_html
from verstka.export.pdf import export_pdf
from verstka.ingest.render import RenderError, find_pdftoppm, find_soffice, pdf_to_images
from verstka.ingest.workspace import TemplateWorkspace
from verstka.matching.matcher import match_outline
from verstka.pipeline.run_manifest import build_run_manifest, write_run_manifest
from verstka.planning.facts import extract_facts
from verstka.planning.outline import adapt_outline, plan_outline, target_slide_count
from verstka.planning.strategies import STRATEGY_NAMES, Strategy, load_strategies
from verstka.providers.registry import ProviderRegistry
from verstka.rendering.renderer import RenderResult, render_deck
from verstka.schemas.audit import AuditReport, Issue
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


def render_outputs(vdir: Path, manifest: TemplateManifest, title: Optional[str], exports: list[str], *, images: bool = True, dpi: int = 110) -> tuple[dict[str, Path], list[Path], list[str], Optional[bool]]:
    """PDF, HTML and slide previews of `vdir/deck.pptx` with a single LibreOffice run.

    Returns (export paths, slide images, warnings, render_ok) — render_ok is None when LibreOffice was not needed
    or is not installed, False when it failed on the deck.
    """
    deck = vdir / "deck.pptx"
    paths: dict[str, Path] = {}
    warnings: list[str] = []
    imgs: list[Path] = []
    render_ok: Optional[bool] = None
    pdf: Optional[Path] = None
    if ("pdf" in exports or images) and find_soffice():
        try:
            pdf = export_pdf(deck, vdir / "deck.pdf")
            render_ok = True
            if "pdf" in exports:
                paths["pdf"] = pdf
        except Exception as e:  # noqa: BLE001
            render_ok = False
            warnings.append(f"export pdf failed: {str(e)[:160]}")
    if images and pdf is not None and find_pdftoppm():
        try:
            imgs = pdf_to_images(pdf, vdir / "slides", dpi=dpi)
        except RenderError as e:
            warnings.append(f"render images failed: {e}")
    if pdf is not None and "pdf" not in exports:
        pdf.unlink(missing_ok=True)
    if "html" in exports:
        try:
            paths["html"] = export_html(deck, manifest, vdir / "deck.html", title=title)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"export html failed: {str(e)[:160]}")
    return paths, imgs, warnings, render_ok


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
    render_images: bool = True,
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
    if providers is not None:
        # brief → decks gets a fixed model budget: past it every model step takes its deterministic path, so a slow
        # or congested backend costs quality, never the 5 minutes a deck may take
        providers = providers.with_deadline(time.monotonic() + providers.limits.time_budget_s)
    ws = TemplateWorkspace.open(manifest.template_id, workspace_root)
    result = GenerateResult(template_id=manifest.template_id, manifest=manifest)
    facts: Optional[FactsExtraction] = None
    fact_warnings: list[str] = []
    if brief is not None and outline is None:
        facts, fact_warnings = extract_facts(brief, skills if use_llm else None, providers if use_llm else None)
    n = len(strategies)
    audit_render = bool(audit_models and use_vlm)  # the VLM checks look at slide images; deterministic ones read XML
    planned: dict[str, tuple[DeckOutline, list[str], float]] = {}
    if outline is None:
        # the strategies are independent: with a model each plan is a chain of 2–3 calls (plan, fact check, repair),
        # so they run side by side and the deck waits for the slowest chain, not for the sum of them
        def _plan(name: str) -> tuple[str, DeckOutline, list[str], float]:
            tp = time.time()
            strategy = all_strategies[name]
            # own copy of the facts: the deterministic planner adds the brief's table series to them
            o, w = plan_outline(brief, manifest, strategy, facts.model_copy(deep=True), skills if use_llm else None, providers if use_llm else None, target=target_slide_count(brief, strategy))
            return name, o, w, round(time.time() - tp, 2)

        report(f"plan: {n} variants", 0.15)
        workers = min(n, providers.limits.max_concurrency) if (use_llm and providers is not None and skills is not None) else 1
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                done = list(ex.map(_plan, strategies))
        else:
            done = [_plan(name) for name in strategies]
        planned = {name: (o, w, sec) for name, o, w, sec in done}
        # a congested endpoint may answer one variant and not the others: the variants whose own model plan failed
        # take the model's content (reshaped for their strategy) rather than a thin plan made by the rules
        order = sorted(planned, key=lambda nm: STRATEGY_NAMES.index(nm) if nm in STRATEGY_NAMES else len(STRATEGY_NAMES))
        donor = next((nm for nm in order if planned[nm][0].planned_by == "model"), None)
        if donor is not None:
            for name in strategies:
                o, w, sec = planned[name]
                if o.planned_by == "model":
                    continue
                st = all_strategies[name]
                adapted = adapt_outline(planned[donor][0], st, manifest, target_slide_count(brief, st), hard_limit=bool(brief.slide_count))
                planned[name] = (adapted, w + [f"own model plan failed: the model plan of «{donor}» adapted to «{name}»"], sec)
    pending: list[dict] = []
    for i, name in enumerate(strategies):
        strategy: Strategy = all_strategies[name]
        ts = time.time()
        timings: dict[str, float] = {"analyze": analyze_s}
        vdir = out_dir / name
        vdir.mkdir(parents=True, exist_ok=True)
        warnings = list(fact_warnings)
        base = 0.15 + 0.7 * i / n
        span = 0.7 / n
        if outline is not None:
            v_outline = outline.model_copy(deep=True)
            v_outline.strategy = name
            timings["plan"] = 0.0
        else:
            v_outline, w, timings["plan"] = planned[name]
            warnings.extend(w)
        plan = match_outline(v_outline, manifest, strategy)
        report(f"{name}: planned {len(v_outline.slides)} slides, rendering", base + span * 0.2)
        tr = time.time()
        render = render_deck(v_outline, plan, manifest, ws, vdir / "deck.pptx", progress=lambda s, f: report(f"{name}: {s}", base + span * (0.2 + 0.4 * f)))
        timings["render"] = round(time.time() - tr, 2)
        warnings.extend(render.warnings)
        audit_report: Optional[AuditReport] = None
        if audit:
            tau = time.time()
            report(f"{name}: audit", base + span * 0.65)
            audit_report = run_audit(vdir / "deck.pptx", manifest, v_outline, ws, providers=providers if audit_models else None, skills=skills if audit_models else None, use_vlm=audit_models and use_vlm, use_llm=audit_models and use_llm, render=audit_render, images_dir=vdir / "slides", strategy=name)
            if autofix and audit_report.summary.errors + audit_report.summary.warnings > 0:
                report(f"{name}: autofix ({audit_report.summary.errors} errors)", base + span * 0.8)
                audit_report, plan, v_outline, rr = autofix_loop(vdir / "deck.pptx", audit_report, v_outline, plan, manifest, ws, providers=providers, skills=skills, use_models=audit_models, images_dir=vdir / "slides", render=audit_render)
                if rr is not None:
                    render = rr
            timings["audit"] = round(time.time() - tau, 2)
        pending.append({"name": name, "ts": ts, "timings": timings, "vdir": vdir, "warnings": warnings, "outline": v_outline, "plan": plan, "render": render, "audit": audit_report})

    # LibreOffice once per deck, all decks at once: the PDF export and the slide previews come from the same PDF
    report("export: pdf, html, slide previews", 0.86)

    def _finish(v: dict) -> dict:
        te = time.time()
        want_images = (render_images or audit) and not (v["audit"] is not None and v["audit"].slide_images)
        v["exports"], v["images"], w, v["render_ok"] = render_outputs(v["vdir"], manifest, v["outline"].title, exports, images=want_images)
        v["warnings"].extend(w)
        if not want_images and v["audit"] is not None:
            v["images"] = [Path(p) for _, p in sorted(v["audit"].slide_images.items())]
        v["timings"]["export"] = round(time.time() - te, 2)
        return v

    workers = min(len(pending), 3) or 1
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            finished = list(ex.map(_finish, pending))
    else:
        finished = [_finish(v) for v in pending]

    for v in finished:
        name, vdir, audit_report = v["name"], v["vdir"], v["audit"]
        if audit_report is not None:
            if v["images"]:
                audit_report.slide_images = {k: str(p) for k, p in enumerate(v["images"], 1)}
            if v["render_ok"] is False:
                audit_report.issues.append(Issue(id="file_opens-0-render", slide=0, check_id="file_opens", severity="warn", kind="deterministic", message="LibreOffice не смог отрендерить файл"))
                audit_report.recompute()
            (vdir / "audit_report.json").write_text(audit_report.model_dump_json(indent=2), encoding="utf-8")
        (vdir / "outline.json").write_text(v["outline"].model_dump_json(indent=2), encoding="utf-8")
        (vdir / "layout_plan.json").write_text(v["plan"].model_dump_json(indent=2), encoding="utf-8")
        export_paths = {"pptx": vdir / "deck.pptx", **v["exports"]}
        timings = v["timings"]
        vr = VariantResult(strategy=name, out_dir=vdir, outline=v["outline"], plan=v["plan"], render=v["render"], images=v["images"], warnings=v["warnings"], seconds=round(time.time() - v["ts"], 2), audit=audit_report, exports=export_paths, timings=timings)
        timings["total"] = vr.seconds
        slides_info = [{"index": s.index, "outline_id": s.outline_id, "mode": s.mode, "pattern_id": s.pattern_id, "composition": s.composition, "warnings": s.warnings} for s in v["render"].slides]
        rm = build_run_manifest(
            template_id=manifest.template_id,
            template_file=manifest.source_file,
            strategy=name,
            brief_hash=_sha(brief.text) if brief else None,
            outline_hash=_sha(v["outline"].model_dump_json()),
            skills=skills,
            providers=providers,
            timings=timings,
            applied_fixes=audit_report.applied_fixes if audit_report else [],
            audit_summary=audit_report.summary.model_dump() if audit_report else {},
            slides=slides_info,
            extra={"warnings": v["warnings"], "exports": {k: str(p) for k, p in export_paths.items()}},
        )
        write_run_manifest(vdir / "run_manifest.json", rm)
        result.variants.append(vr)
        report(f"{name}: done in {vr.seconds}s", 0.86 + 0.14 * len(result.variants) / n)
    result.seconds = round(time.time() - t0, 2)
    return result
