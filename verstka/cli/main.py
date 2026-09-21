"""verstka CLI: analyze (more commands arrive with later phases)."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Optional

import typer
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
    path = models or (_REPO_ROOT / "configs" / "models.yaml")
    return ProviderRegistry.from_yaml(path)


@app.callback()
def _root(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging")) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")


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
        manifest = analyze_template(
            template,
            workspace_root=workspace,
            providers=providers,
            skills=skills,
            use_llm=not no_llm,
            use_vlm=not no_vlm,
            tag_assets=tag_assets,
            render=not no_render,
            force=force,
            max_workers=workers,
            progress=lambda stage, frac: status.update(f"[{frac:4.0%}] {stage}"),
        )
    t = manifest.tokens
    console.print(f"[bold]{manifest.source_file}[/bold] → template_id [cyan]{manifest.template_id}[/cyan]")
    console.print(f"{manifest.n_slides} slides · {len(manifest.patterns)} patterns · {len(manifest.assets)} assets · {len(t.chrome)} chrome elements · fonts: {', '.join(f.family for f in t.typography.families[:3])}")
    console.print("Scale: " + ", ".join(f"{s.role} {s.size_pt:g}" for s in t.typography.scale))
    tbl = Table(title="Colours", show_lines=False)
    tbl.add_column("hex")
    tbl.add_column("role")
    tbl.add_column("weight", justify="right")
    for c in t.colors[:12]:
        tbl.add_row(f"[#{c.hex}]■[/] #{c.hex}", c.role or "", f"{c.weight:g}")
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
