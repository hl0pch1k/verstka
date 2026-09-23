"""verstka CLI: analyze, plan, generate, audit, export."""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table

from verstka.providers.registry import ProviderRegistry
from verstka.skills_registry.registry import SkillsRegistry

app = typer.Typer(help="Verstka — reads any PPTX template as a set of rules and generates decks in its style.", no_args_is_help=True)
console = Console()

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _providers(models: Optional[Path], need: bool) -> Optional[ProviderRegistry]:
    if not need:
        return None
    from verstka.providers.registry import default_models_path

    return ProviderRegistry.from_yaml(models or default_models_path())


@app.callback()
def _root(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging")) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


@app.command()
def analyze(
    template: Path = typer.Argument(..., exists=True, readable=True, help="Path to a .pptx template or past deck"),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w", help="Workspace root (default ./workspace or $VERSTKA_WORKSPACE)"),
    models: Optional[Path] = typer.Option(None, "--models", help="models.yaml with provider roles"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM classification"),
    no_vlm: bool = typer.Option(False, "--no-vlm", help="Skip VLM checks on rendered slides"),
    tag_assets: bool = typer.Option(False, "--tag-assets", help="Tag large assets with the VLM"),
    no_render: bool = typer.Option(False, "--no-render", help="Skip LibreOffice rendering (no thumbnails, no VLM)"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-analyze even if cached"),
    workers: int = typer.Option(4, "--workers", help="Parallel model calls"),
) -> None:
    """Decompose a template into tokens, patterns, components, assets and rules."""
    from verstka.analysis.manifest import analyze_template

    use_models = not (no_llm and no_vlm)
    providers = _providers(models, use_models)
    skills = SkillsRegistry.load() if use_models else None
    with console.status("Analyzing template…") as status:
        manifest = analyze_template(template, workspace_root=workspace, providers=providers, skills=skills, use_llm=not no_llm, use_vlm=not no_vlm, tag_assets=tag_assets, render=not no_render, force=force, max_workers=workers, progress=lambda stage, frac: status.update(f"[{frac:4.0%}] {stage}"))
    t = manifest.tokens
    console.print(f"[bold]{manifest.source_file}[/bold] → template_id [cyan]{manifest.template_id}[/cyan]")
    console.print(f"{manifest.n_slides} slides · {len(manifest.patterns)} patterns · {len(manifest.assets)} assets · {len(t.chrome)} chrome elements · fonts: {', '.join(f.family for f in t.typography.families[:3])}")
    console.print("Scale: " + ", ".join(f"{s.role} {s.size_pt:g}" for s in t.typography.scale))
    tbl = Table(title="Colours")
    tbl.add_column("hex")
    tbl.add_column("roles")
    tbl.add_column("weight", justify="right")
    for c in t.colors[:12]:
        tbl.add_row(f"[#{c.hex}]■[/] #{c.hex}", ", ".join(c.roles), f"{c.weight:g}")
    console.print(tbl)
    kinds = Counter(p.kind.value for p in manifest.patterns)
    tbl2 = Table(title="Patterns by kind")
    tbl2.add_column("kind")
    tbl2.add_column("count", justify="right")
    for k, v in kinds.most_common():
        tbl2.add_row(k, str(v))
    console.print(tbl2)
    if manifest.warnings:
        console.print(f"[yellow]{len(manifest.warnings)} warnings[/yellow] (see manifest.json)")
    ws_dir = Path(workspace or "workspace") / "templates" / manifest.template_id
    console.print(f"Manifest: {ws_dir / 'manifest.json'}\nGallery:  {ws_dir / 'gallery.html'}")


def _load_run_config(path: Optional[Path]) -> dict:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@app.command()
def generate(
    template: Optional[Path] = typer.Option(None, "--template", "-t", help="Template .pptx"),
    brief: Optional[Path] = typer.Option(None, "--brief", "-b", help="Brief (.md/.txt/.json)"),
    outline: Optional[Path] = typer.Option(None, "--outline", help="Ready outline.json (skips planning)"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="run.yaml with all options (reproducible run)"),
    strategy: str = typer.Option("all", "--strategy", "-s", help="structured | visual | compact | all"),
    slides: Optional[int] = typer.Option(None, "--slides", help="Target slide count"),
    out: Path = typer.Option(Path("out"), "--out", "-o", help="Output directory"),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    models: Optional[Path] = typer.Option(None, "--models"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Deterministic planning and analysis (no model calls)"),
    no_vlm: bool = typer.Option(False, "--no-vlm"),
    no_audit: bool = typer.Option(False, "--no-audit"),
    no_autofix: bool = typer.Option(False, "--no-autofix"),
    audit_models: bool = typer.Option(False, "--audit-models", help="Run VLM/LLM content checks in the audit"),
    export: str = typer.Option("pptx", "--export", help="pptx | pdf | html | all (comma separated)"),
    render: bool = typer.Option(False, "--render", help="Render slide images even without audit"),
) -> None:
    """Generate three layout variants (or one) from a template and a brief, audit, autofix and export them."""
    from verstka.pipeline.generate import generate_variants
    from verstka.planning.brief import load_brief
    from verstka.schemas.outline import DeckOutline

    cfg = _load_run_config(config)
    template = template or (Path(cfg["template"]) if cfg.get("template") else None)
    brief = brief or (Path(cfg["brief"]) if cfg.get("brief") else None)
    outline = outline or (Path(cfg["outline"]) if cfg.get("outline") else None)
    strategy = cfg.get("strategy", strategy) if strategy == "all" else strategy
    slides = slides or cfg.get("slides")
    out = Path(cfg.get("out", out)) if config else out
    export = cfg.get("export", export)
    no_llm = no_llm or bool(cfg.get("no_llm", False))
    no_vlm = no_vlm or bool(cfg.get("no_vlm", False))
    no_audit = no_audit or bool(cfg.get("no_audit", False))
    no_autofix = no_autofix or bool(cfg.get("no_autofix", False))
    audit_models = audit_models or bool(cfg.get("audit_models", False))
    if template is None or (brief is None and outline is None):
        raise typer.BadParameter("--template and (--brief or --outline) are required (or a --config run.yaml)")
    strategies = None if strategy in ("all", None) else [s.strip() for s in str(strategy).split(",")]
    exports = ["pdf", "html"] if export == "all" else [e.strip() for e in export.split(",") if e.strip() and e.strip() != "pptx"]
    use_models = not no_llm
    providers = _providers(models, use_models or audit_models)
    skills = SkillsRegistry.load() if (use_models or audit_models) else None
    brief_obj = load_brief(brief) if brief else None
    if brief_obj is not None and slides:
        brief_obj.slide_count = int(slides)
    if brief_obj is not None and cfg.get("audience"):
        brief_obj.audience = cfg["audience"]
    outline_obj = DeckOutline.model_validate_json(Path(outline).read_text(encoding="utf-8")) if outline else None
    with console.status("Generating…") as status:
        res = generate_variants(
            template,
            brief=brief_obj,
            outline=outline_obj,
            strategies=strategies,
            out_dir=out,
            workspace_root=workspace,
            providers=providers,
            skills=skills,
            use_llm=not no_llm,
            use_vlm=not no_vlm,
            render_images=render,
            audit=not no_audit,
            autofix=not no_autofix,
            audit_models=audit_models,
            exports=exports,
            progress=lambda stage, frac: status.update(f"[{frac:4.0%}] {stage}"),
        )
    console.print(f"[bold]{res.manifest.source_file}[/bold] · template {res.template_id} · {res.seconds}s total")
    for v in res.variants:
        tbl = Table(title=f"{v.strategy}: {len(v.outline.slides)} slides in {v.seconds}s" + (f" · audit score {v.audit.summary.score} (errors {v.audit.summary.errors}, warnings {v.audit.summary.warnings}, fixes {len(v.audit.applied_fixes)})" if v.audit else ""))
        tbl.add_column("#", justify="right")
        tbl.add_column("kind")
        tbl.add_column("headline")
        tbl.add_column("mode")
        tbl.add_column("pattern / composition")
        tbl.add_column("issues", justify="right")
        per_slide = v.audit.per_slide if v.audit else {}
        for s in v.render.slides:
            osl = next((o for o in v.outline.slides if o.id == s.outline_id), None)
            tbl.add_row(str(s.index), osl.kind.value if osl else "", (osl.headline[:48] if osl else ""), s.mode, s.pattern_id or s.composition or "", str(len(per_slide.get(s.index, []))))
        console.print(tbl)
        console.print("  " + " · ".join(f"{k}: {p}" for k, p in v.exports.items()))
    console.print(f"Output: {out.resolve()}")


@app.command()
def audit(
    deck: Path = typer.Argument(..., exists=True, help="Generated deck.pptx"),
    template: Path = typer.Option(..., "--template", "-t", help="Template .pptx the deck was built on"),
    outline: Optional[Path] = typer.Option(None, "--outline", help="outline.json of the deck (enables content checks)"),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    models: Optional[Path] = typer.Option(None, "--models"),
    with_models: bool = typer.Option(False, "--with-models", help="Run VLM/LLM content checks"),
    no_render: bool = typer.Option(False, "--no-render"),
    out: Optional[Path] = typer.Option(None, "--out", help="Where to write audit_report.json"),
) -> None:
    """Audit a deck against its template's rules (Appendix 1 checks)."""
    from verstka.analysis.manifest import analyze_template
    from verstka.audit.runner import run_audit
    from verstka.ingest.workspace import TemplateWorkspace
    from verstka.schemas.outline import DeckOutline

    manifest = analyze_template(template, workspace_root=workspace, use_llm=False, use_vlm=False, render=False)
    ws = TemplateWorkspace.open(manifest.template_id, workspace)
    outline_obj = DeckOutline.model_validate_json(outline.read_text(encoding="utf-8")) if outline else None
    providers = _providers(models, with_models)
    skills = SkillsRegistry.load() if with_models else None
    report = run_audit(deck, manifest, outline_obj, ws, providers=providers, skills=skills, use_vlm=with_models, use_llm=with_models, render=not no_render, images_dir=deck.parent / "slides")
    target = out or deck.parent / "audit_report.json"
    target.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"score {report.summary.score} · errors {report.summary.errors} · warnings {report.summary.warnings} · model flags {report.summary.model_flags} · checks {len(report.summary.checks_run)}")
    tbl = Table(title="Issues")
    tbl.add_column("slide", justify="right")
    tbl.add_column("severity")
    tbl.add_column("check")
    tbl.add_column("message")
    tbl.add_column("fix")
    for i in sorted(report.issues, key=lambda i: (i.slide, {"error": 0, "warn": 1, "info": 2}[i.severity])):
        tbl.add_row(str(i.slide), i.severity, i.check_id, i.message[:80], i.autofix.action if i.autofix else "")
    console.print(tbl)
    console.print(f"Report: {target}")


@app.command()
def export(
    deck: Path = typer.Argument(..., exists=True, help="deck.pptx"),
    template: Path = typer.Option(..., "--template", "-t", help="Template .pptx (for tokens used in HTML)"),
    fmt: str = typer.Option("all", "--format", "-f", help="pdf | html | all"),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Export a deck to PDF and/or single-file HTML."""
    from verstka.analysis.manifest import analyze_template
    from verstka.export.html import export_html
    from verstka.export.pdf import export_pdf

    manifest = analyze_template(template, workspace_root=workspace, use_llm=False, use_vlm=False, render=False)
    if fmt in ("pdf", "all"):
        console.print(f"pdf:  {export_pdf(deck)}")
    if fmt in ("html", "all"):
        console.print(f"html: {export_html(deck, manifest)}")


@app.command()
def skills() -> None:
    """List skills and agents with versions and content hashes."""
    reg = SkillsRegistry.load()
    tbl = Table(title="Skills")
    tbl.add_column("name")
    tbl.add_column("version")
    tbl.add_column("role")
    tbl.add_column("sha256")
    for name, spec in sorted(reg.skills.items()):
        tbl.add_row(name, spec.version, spec.role, spec.sha256[:12])
    console.print(tbl)


@app.command(name="checks")
def list_checks() -> None:
    """List audit checks (deterministic and model)."""
    from verstka.audit.model_checks import DECK_COHERENCE, SLIDE_CONTENT
    from verstka.audit.registry import all_checks

    tbl = Table(title="Audit checks")
    tbl.add_column("id")
    tbl.add_column("kind")
    tbl.add_column("severity")
    tbl.add_column("category")
    tbl.add_column("title")
    for spec, _ in all_checks():
        tbl.add_row(spec.id, spec.kind, spec.severity, spec.category, spec.title)
    for spec in (SLIDE_CONTENT, DECK_COHERENCE):
        tbl.add_row(spec.id, spec.kind, spec.severity, spec.category, spec.title)
    console.print(tbl)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    port: int = typer.Option(8000, "--port", "-p"),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w", help="Workspace root (default ./workspace or $VERSTKA_WORKSPACE)"),
    models: Optional[Path] = typer.Option(None, "--models", help="models.yaml with provider roles"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (development)"),
) -> None:
    """Run the web service: API on /api and the React UI on / (after `npm run build` in web/)."""
    import os

    import uvicorn

    if workspace:
        os.environ["VERSTKA_WORKSPACE"] = str(workspace.resolve())
    if models:
        os.environ["VERSTKA_MODELS"] = str(models.resolve())
    if not (_REPO_ROOT / "web" / "dist" / "index.html").exists():
        console.print("[yellow]web/dist not found: only the API is served. Build the UI: cd web && npm install && npm run build[/yellow]")
    console.print(f"Verstka → http://{host}:{port}")
    uvicorn.run("verstka.api.app:app", host=host, port=port, reload=reload, log_level="info")
