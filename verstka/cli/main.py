"""verstka CLI: analyze, plan, generate, audit, export."""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table

from verstka.providers.registry import ProviderRegistry
from verstka.ru import ru_count
from verstka.skills_registry.registry import SkillsRegistry

app = typer.Typer(help="Verstka — reads any PPTX template as a set of rules and generates decks in its style.", no_args_is_help=True)
console = Console()

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _image_provider(models: Path):
    """The t2i role of the models config given with --models (the same config as the text models)."""
    from verstka.images.providers import load_image_provider

    return load_image_provider(models)


def _say_free_places(vdir: Path) -> None:
    """The picture places left free in the finished deck and why (a place the person asked for stays: the owner's rule)."""
    try:
        from verstka.images.fill import read_records

        for r in read_records(vdir):
            if r.get("status") != "generated" and r.get("why"):
                console.print(f"  [yellow]слайд {r.get('slide')}: место под изображение оставлено — {r.get('why')}[/yellow]")
    except Exception:  # noqa: BLE001 - a line of the report, never the build
        pass


def _pictures_switch(models: Optional[Path], no_models: bool, asked: Optional[bool] = None) -> Optional[bool]:
    """The pictures of a CLI build, as in the interface: on when the models config has a text-to-image model (None —
    the config's own switch, configs/images.yaml), off without models, off when --models names a config without a
    t2i role (the jury of 20.10: such a config still drew pictures with the default profile's Z-Image), `asked` (run.yaml
    «pictures») wins when given."""
    if no_models:
        return False
    if asked is not None:
        return bool(asked) and (models is None or _image_provider(models) is not None)
    if models is not None and _image_provider(models) is None:
        return False
    return None


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
    console.print(f"[bold]{manifest.source_file}[/bold] → шаблон [cyan]{manifest.template_id}[/cyan]")
    console.print(f"{ru_count(manifest.n_slides, 'слайд', 'слайда', 'слайдов')} · {ru_count(len(manifest.patterns), 'макет', 'макета', 'макетов')} · "
                  f"{ru_count(len(manifest.assets), 'картинка', 'картинки', 'картинок')} · {ru_count(len(t.chrome), 'постоянный элемент', 'постоянных элемента', 'постоянных элементов')} · "
                  f"шрифты: {', '.join(f.family for f in t.typography.families[:3])}")
    console.print("Кегли: " + ", ".join(f"{s.role} {s.size_pt:g}" for s in t.typography.scale))
    tbl = Table(title="Цвета")
    tbl.add_column("HEX")
    tbl.add_column("роли")
    tbl.add_column("вес", justify="right")
    for c in t.colors[:12]:
        tbl.add_row(f"[#{c.hex}]■[/] #{c.hex}", ", ".join(c.roles), f"{c.weight:g}")
    console.print(tbl)
    kinds = Counter(p.kind.value for p in manifest.patterns)
    tbl2 = Table(title="Макеты по типам")
    tbl2.add_column("тип")
    tbl2.add_column("сколько", justify="right")
    for k, v in kinds.most_common():
        tbl2.add_row(k, str(v))
    console.print(tbl2)
    if manifest.warnings:
        console.print(f"[yellow]{ru_count(len(manifest.warnings), 'предупреждение', 'предупреждения', 'предупреждений')}[/yellow] (см. manifest.json)")
    ws_dir = Path(workspace or "workspace") / "templates" / manifest.template_id
    console.print(f"Разбор:  {ws_dir / 'manifest.json'}\nГалерея: {ws_dir / 'gallery.html'}")


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
    audit_models: Optional[bool] = typer.Option(None, "--audit-models/--no-audit-models", help="The model's content checks of the finished decks (the 11 questions of the ТЗ's appendix 1, the deck's coherence); default: on with models"),
    no_eyes: bool = typer.Option(False, "--no-eyes", help="Skip «Взгляд дизайнера»: the vision model's look at the finished slides"),
    export: str = typer.Option("pptx", "--export", help="pptx | pdf | html | all (comma separated)"),
    render: bool = typer.Option(False, "--render", help="Render slide images even without audit"),
    data: Optional[list[str]] = typer.Option(None, "--data", "-d", help="Data files (CSV, XLSX, JSON, TXT/MD with a table) or a folder of them; repeat --data for several, or give one comma-separated value: the deck becomes a data story"),
    brand: Optional[str] = typer.Option(None, "--brand", help="Brandbook: tokens JSON, PDF guideline, a folder or .zip with logos, or a Figma link — the deck is laid out on the template's branded copy"),
    brand_priority: str = typer.Option("brand", "--brand-priority", help="brand (the brandbook wins over the template) | template (the brand only adds what the template lacks)"),
    pick_fonts: bool = typer.Option(True, "--pick-fonts/--no-pick-fonts", help="Pick a font pair for a template set in standard fonts (Arial, Calibri…): a copy of the template with the fonts embedded; a template with its own font is left as it is"),
    kb: Optional[list[str]] = typer.Option(None, "--kb", help="Knowledge base: an id from the workspace, or documents (DOCX, PDF, MD, TXT), folders, .zip archives and public page links — the writer takes the deck's facts from them, each with its source; repeat --kb for several"),
) -> None:
    """Generate three layout variants (or one) from a template and a brief (and data files, a brandbook, a knowledge
    base), audit, autofix and export them. The brief may be a DOCX or PDF document: its text (headings, lists, tables
    of words) is the brief, its tables of figures become data files."""
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
    if audit_models is None:
        audit_models = bool(cfg["audit_models"]) if "audit_models" in cfg else not (no_llm or no_vlm)
    no_eyes = no_eyes or bool(cfg.get("no_eyes", False))
    data = list(data or []) or [str(x) for x in (cfg.get("data") or [])]
    brand = brand or cfg.get("brand")
    brand_priority = cfg.get("brand_priority", brand_priority) if brand_priority == "brand" else brand_priority
    if brand_priority not in ("brand", "template"):
        raise typer.BadParameter("--brand-priority: «brand» (важнее брендбук) или «template» (важнее шаблон)")
    if template is None or (brief is None and outline is None and not data):
        raise typer.BadParameter("нужны --template и что-то из --brief, --outline, --data (или --config run.yaml)")
    if data:
        _data_files(data)  # a missing data file is said at once, before the template's analysis and the font pick
    strategies = None if strategy in ("all", None) else [s.strip() for s in str(strategy).split(",")]
    exports = ["pdf", "html"] if export == "all" else [e.strip() for e in export.split(",") if e.strip() and e.strip() != "pptx"]
    use_models = not no_llm
    providers = _providers(models, use_models or audit_models)
    skills = SkillsRegistry.load() if (use_models or audit_models) else None
    brief_obj = None
    if brief and Path(brief).suffix.lower() in _DOC_BRIEF_EXTS:
        brief_obj, doc_tables = _document_brief(Path(brief))
        if doc_tables and not data:
            data = [str(brief)]  # its tables of figures: the deck becomes a data story told by the document's text
            console.print(f"Документ «{Path(brief).name}»: текст — бриф, {ru_count(doc_tables, 'таблица с цифрами', 'таблицы с цифрами', 'таблиц с цифрами')} — данные")
    elif brief:
        brief_obj = load_brief(brief)
    if brief_obj is not None and slides:
        brief_obj.slide_count = int(slides)
    if brief_obj is not None and cfg.get("audience"):
        brief_obj.audience = cfg["audience"]
    outline_obj = DeckOutline.model_validate_json(Path(outline).read_text(encoding="utf-8")) if outline else None
    template = Path(template)
    story = None
    steps: dict = {}  # the steps before the pipeline (brandbook, data story): their seconds go into the run manifest
    brand_stats: list = []  # the model calls of the brandbook's read and the template's analysis
    with console.status("Generating…") as status:
        if brand:
            tb = time.monotonic()
            template = _branded(template, brand, brand_priority, workspace, providers, skills, use_vlm=not no_vlm and use_models, use_llm=use_models, status=status, stats=brand_stats)
            steps["brand"] = time.monotonic() - tb
        tf = time.monotonic()
        template = _fonted(template, workspace, enabled=bool(cfg.get("pick_fonts", pick_fonts)), brand_fonts=_brand_has_fonts(brand), status=status)
        steps["fonts"] = time.monotonic() - tf
        if data and outline_obj is None:
            from verstka.data.story import build_data_story

            tables = _read_data(data)
            try:
                story = build_data_story(
                    brief_obj, tables, use_llm=use_models, skills=skills if use_models else None,
                    providers=providers if use_models else None, slide_count=int(slides) if slides else None,
                    progress=lambda stage, frac=None, **_: status.update(f"[данные] {stage}"),
                )
            except Exception as e:  # noqa: BLE001 - the data story's failure never aborts the generation (F9)
                console.print(f"[yellow]История данных с моделью не построилась ({str(e)[:160]}) — по правилам[/yellow]")
                story = build_data_story(
                    brief_obj, tables, use_llm=False, slide_count=int(slides) if slides else None,
                    progress=lambda stage, frac=None, **_: status.update(f"[данные] {stage}"),
                )
            outline_obj, data_brief, brief_obj = story.outline, brief_obj, None  # the data deck's figures are checked against the data
            kb_items = list(kb or []) or [str(x) for x in (cfg.get("kb") or [])]
            if kb_items:
                # план + данные + база знаний: слайды по базе — для пунктов, которых нет в данных
                from verstka.knowledge.with_data import add_knowledge
                from verstka.pipeline.generate import _knowledge

                kref = _knowledge(_knowledge_base(kb_items, workspace), Path(workspace) if workspace else _default_root())
                if kref is not None:
                    part = add_knowledge(outline_obj, data_brief, kref, skills=skills if use_models else None, providers=providers if use_models else None,
                                         tables=tables)
                    outline_obj = part.outline
                    for line in part.log:
                        console.print(f"  {line}")
                    if part.writer is not None:
                        Path(out).mkdir(parents=True, exist_ok=True)
                        part.writer.write_files(Path(out))
                kb = None  # the base is used: the pipeline gets the outline
            for line in story.log:
                console.print(f"  {line}")
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
            eyes=False if no_eyes else None,
            exports=exports,
            # «without models» means no model at all: the pictures are off too; --models drives the pictures as well — a
            # config without a t2i role switches them off (never the default profile's model behind its back)
            pictures=_pictures_switch(models, no_llm and no_vlm, cfg.get("pictures")),
            image_provider=_image_provider(models) if models and not (no_llm and no_vlm) else None,
            progress=lambda stage, frac: status.update(f"[{frac:4.0%}] {stage}"),
            knowledge_id=_knowledge_base(list(kb or []) or ([] if story is not None else [str(x) for x in (cfg.get("kb") or [])]), workspace),
        )
    from verstka.data.story import stamp_steps

    if story is not None:
        steps["data"] = story.seconds
    stamp_steps(res, steps)  # (before the data story's own stamp: that one writes the deck's story beside the manifest)
    if brand_stats:
        from verstka.data.story import stamp_usage

        stamp_usage(res, brand_stats, "brand")
    if story is not None:
        from verstka.data.story import stamp_variants

        stamp_variants(res, story, out)
        made = f"связку написала модель ({story.model})" if story.model_used else "формулировки — по правилам, без модели"
        refused = f", проверка фактов отклонила {ru_count(len(story.rejected), 'переформулировку', 'переформулировки', 'переформулировок')}" if story.rejected else ""
        console.print(f"История из данных: {ru_count(len(story.plans), 'набор', 'набора', 'наборов')}, "
                      f"{ru_count(len(story.outline.slides), 'слайд', 'слайда', 'слайдов')}; {made}{refused}")
    console.print(f"[bold]{res.manifest.source_file}[/bold] · шаблон {res.template_id} · всего {res.seconds} с")
    for v in res.variants:
        a = v.audit.summary if v.audit else None
        tbl = Table(title=f"{v.strategy}: {ru_count(len(v.outline.slides), 'слайд', 'слайда', 'слайдов')} за {v.seconds} с"
                    + (f" · проверка: {a.score} из 100 (ошибок {a.errors}, предупреждений {a.warnings}, исправлений {len(v.audit.applied_fixes)})" if a else ""))
        tbl.add_column("№", justify="right")
        tbl.add_column("тип")
        tbl.add_column("заголовок")
        tbl.add_column("режим")
        tbl.add_column("макет / композиция")
        tbl.add_column("замечаний", justify="right")
        per_slide = v.audit.per_slide if v.audit else {}
        for s in v.render.slides:
            osl = next((o for o in v.outline.slides if o.id == s.outline_id), None)
            tbl.add_row(str(s.index), osl.kind.value if osl else "", (osl.headline[:48] if osl else ""), s.mode, s.pattern_id or s.composition or "", str(len(per_slide.get(s.index, []))))
        console.print(tbl)
        _say_free_places(v.out_dir)
        console.print("  " + " · ".join(f"{k}: {p}" for k, p in v.exports.items()))
    console.print(f"Готово: {out.resolve()}")


_SEVERITY_RU = {"error": "ошибка", "warn": "предупреждение", "info": "заметка"}
_DATA_EXT = {".csv", ".tsv", ".xlsx", ".json", ".txt", ".md"}
_NOT_DATA = {"scenario.md", "readme.md"}


def _data_files(items: list[str]) -> list[Path]:
    """--data values → files: a file as given, a folder → its data files (not SCENARIO.md / README.md), a value with
    commas → several."""
    out: list[Path] = []
    for item in items:
        for part in [x.strip() for x in str(item).split(",") if x.strip()]:
            p = Path(part)
            if p.is_dir():
                out += [f for f in sorted(p.iterdir()) if f.is_file() and f.suffix.lower() in _DATA_EXT and f.name.lower() not in _NOT_DATA]
            elif p.is_file():
                out.append(p)
            else:
                raise typer.BadParameter(f"--data: не найден файл или папка «{part}»")
    return list(dict.fromkeys(out))


_DOC_BRIEF_EXTS = (".docx", ".docm", ".pdf", ".doc", ".rtf", ".odt")


def _fonted(template: Path, workspace: Optional[Path], *, enabled: bool, brand_fonts: bool, status=None) -> Path:
    """The template the deck is laid out on: its copy with a picked font pair when it is set in standard fonts
    (verstka/brand/fontpick.py); else the template itself."""
    from verstka.analysis.manifest import analyze_template
    from verstka.brand.fontpick import fonted_template
    from verstka.ingest.workspace import TemplateWorkspace

    root = Path(workspace) if workspace else _default_root()
    try:
        m = analyze_template(template, workspace_root=root, use_llm=False, use_vlm=False)
        tid, ch = fonted_template(m.template_id, enabled=enabled, brand_fonts=brand_fonts, workspace_root=root,
                                  progress=(lambda stage, frac: status.update(f"[шрифты] {stage}")) if status is not None else None)
    except Exception as e:  # noqa: BLE001 - the template as it is
        console.print(f"[yellow]Шрифты не подобраны ({str(e)[:120]}) — шаблон как есть[/yellow]")
        return template
    console.print(f"Шрифты: {ch.heading} / {ch.body} — {ch.reason}" if ch.apply else f"Шрифты: {ch.reason}")
    return TemplateWorkspace.open(tid, root).source if tid != m.template_id else template


def _brand_has_fonts(brand: Optional[str]) -> bool:
    """A brandbook given (its fonts are stronger than the pick): a tokens JSON names its fonts; a PDF or a folder —
    assumed to (it is read later, on the branded copy)."""
    if not brand:
        return False
    p = Path(str(brand))
    if p.suffix.lower() == ".json" and p.is_file():
        try:
            return bool(json.loads(p.read_text(encoding="utf-8")).get("fonts"))
        except (OSError, ValueError, AttributeError):
            return True
    return True


def _default_root() -> Path:
    from verstka.ingest.workspace import default_workspace_root

    return default_workspace_root()


def _document_brief(path: Path):
    """A DOCX / PDF brief: (its text as the brief, how many tables of figures it has)."""
    from verstka.ingest.documents import DocumentError, read_document
    from verstka.planning.brief import parse_brief_text

    try:
        doc = read_document(path.name, path.read_bytes())
    except DocumentError as e:
        raise typer.BadParameter(f"--brief: {e}")
    if doc.data_first:  # mostly tables of figures: the text is the brief, the tables — data files
        return parse_brief_text(doc.markdown(data_tables=False)), len(doc.data_tables)
    return parse_brief_text(doc.markdown()), 0  # a document of its own text: laid out whole, its tables inline


def _knowledge_base(items: list[str], workspace: Optional[Path]) -> Optional[str]:
    """--kb values → the id of the knowledge base: an id of the workspace's base as it is, else a new base of the
    documents, folders, archives and links given."""
    if not items:
        return None
    from verstka.ingest.workspace import default_workspace_root
    from verstka.knowledge.store import KnowledgeBase, KnowledgeError

    root = Path(workspace) if workspace else default_workspace_root()
    if len(items) == 1 and KnowledgeBase.open(root, items[0]) is not None:
        return items[0]
    base = KnowledgeBase.create(root, "База знаний")
    for item in items:
        for part in [x.strip() for x in str(item).split(",") if x.strip()]:
            if part.startswith(("http://", "https://")):
                try:
                    got = base.add_url(part)
                except KnowledgeError as e:
                    console.print(f"[yellow]--kb: {part} — {e}[/yellow]")
                    continue
            else:
                p = Path(part)
                files = sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else [p] if p.is_file() else []
                if not files:
                    raise typer.BadParameter(f"--kb: не найден файл или папка «{part}»")
                got = None
                for f in files:
                    r = base.add_file(f.name, f.read_bytes())
                    for sk in r.skipped:
                        console.print(f"[yellow]--kb: «{sk['name']}» — {sk['reason']}[/yellow]")
                    got = r
            if got is not None:
                for d in got.docs:
                    console.print(f"База знаний: «{d['title']}» — {ru_count(d['fragments'], 'фрагмент', 'фрагмента', 'фрагментов')}")
    if not base.docs:
        raise typer.BadParameter("--kb: ни один документ не прочитан")
    console.print(f"База знаний {base.id}: {ru_count(len(base.docs), 'документ', 'документа', 'документов')}")
    return base.id


def _read_data(items: list[str]):
    from verstka.data.readers import DataReadError, read_file
    from verstka.ingest.documents import DocumentError, document_tables

    tables = []
    for f in _data_files(items):
        if f.suffix.lower() in _DOC_BRIEF_EXTS:
            try:
                tables += document_tables(f.name, f.read_bytes())
            except (DocumentError, DataReadError) as e:
                raise typer.BadParameter(f"--data: «{f.name}» — {e}")
            continue
        try:
            tables += read_file(f)
        except DataReadError as e:
            raise typer.BadParameter(f"--data: «{f.name}» — {e}")
    if not tables:
        raise typer.BadParameter("--data: таблиц не нашлось")
    return tables


def _branded(template: Path, brand: str, priority: str, workspace: Optional[Path], providers, skills, *, use_vlm: bool, status, use_llm: bool = False, stats: Optional[list] = None) -> Path:
    """The template's branded copy (verstka/brand/apply.py): the brandbook read (its logos kept in the workspace's
    brandbooks/<hash>/), applied to the analysed template; returns the copy's source.pptx."""
    import hashlib

    from verstka.analysis.manifest import analyze_template
    from verstka.brand.apply import branded_template
    from verstka.brand.read import read_brandbook
    from verstka.ingest.workspace import TemplateWorkspace, default_workspace_root

    root = Path(workspace) if workspace else default_workspace_root()
    if providers is not None and stats is not None:
        # the brandbook's read and the template's analysis are model calls of the run too: counted in its usage
        from verstka.pipeline.generate import _recording

        providers, _ = _recording(providers, stats)
    status.update("[брендбук] читаю брендбук")
    key = hashlib.sha256(str(Path(brand).resolve() if Path(brand).exists() else brand).encode("utf-8")).hexdigest()[:16]
    assets = root / "brandbooks" / f"cli-{key}"
    assets.mkdir(parents=True, exist_ok=True)
    spec = read_brandbook(brand, providers=providers if use_vlm else None, skills=skills if use_vlm else None, use_vlm=use_vlm, assets_dir=assets)
    spec.id = assets.name
    # (with models on, the template met here for the first time is analysed with them: the cache a later model run
    # reuses is not the poorer no-model one)
    m = analyze_template(template, workspace_root=root, providers=providers if (use_llm or use_vlm) else None, skills=skills if (use_llm or use_vlm) else None,
                         use_llm=use_llm, use_vlm=use_vlm, progress=lambda s, f: status.update(f"[брендбук] разбор шаблона: {s}"))
    tid = branded_template(m.template_id, spec, priority, workspace_root=root, brand_dir=assets, progress=lambda s, f: status.update(f"[брендбук] {s}"))
    important = "брендбук" if priority == "brand" else "шаблон"
    console.print(f"Брендбук «{spec.name or Path(brand).name}» → брендированная копия шаблона {tid} (при расхождении важнее {important})")
    from verstka.brand.apply import branded_warnings

    for w in branded_warnings(tid, root):
        console.print(f"[yellow]брендбук:[/yellow] {w}")
    return TemplateWorkspace.open(tid, root).source


@app.command(name="kb")
def knowledge(
    items: list[str] = typer.Argument(..., help="Documents (DOCX, PDF, MD, TXT, HTML), folders, .zip archives, public page links"),
    name: str = typer.Option("База знаний", "--name", help="The base's name"),
    search: Optional[str] = typer.Option(None, "--search", "-q", help="Search the base right away"),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
) -> None:
    """Build a knowledge base in the workspace from documents and links (local index, no embeddings); prints its id for
    `generate --kb <id>`."""
    from verstka.ingest.workspace import default_workspace_root
    from verstka.knowledge.reference import KbReference
    from verstka.knowledge.store import KnowledgeBase

    kid = _knowledge_base(items, workspace)
    root = Path(workspace) if workspace else default_workspace_root()
    kbase = KnowledgeBase.open(root, kid)
    if name and kbase is not None:
        m = kbase.meta()
        m["name"] = name
        kbase._write_meta(m)
    if search and kbase is not None:
        ref = KbReference(kbase)
        for f, sc in ref.search.top(search, 5):
            console.print(f"[bold]{sc:.2f}[/bold] {ref.label(f)}\n  {' '.join(f.text.split())[:300]}")
    console.print(kid)


@app.command()
def audit(
    deck: Path = typer.Argument(..., exists=True, help="Generated deck.pptx"),
    template: Path = typer.Option(..., "--template", "-t", help="Template .pptx the deck was built on"),
    outline: Optional[Path] = typer.Option(None, "--outline", help="outline.json of the deck (enables content checks)"),
    brief: Optional[Path] = typer.Option(None, "--brief", help="The source text: every figure on the slides is compared with it"),
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
    report = run_audit(deck, manifest, outline_obj, ws, providers=providers, skills=skills, use_vlm=with_models, use_llm=with_models, render=not no_render, images_dir=deck.parent / "slides", brief_text=brief.read_text(encoding="utf-8") if brief else None)
    target = out or deck.parent / "audit_report.json"
    target.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    sm = report.summary
    console.print(f"оценка {sm.score} из 100 · ошибок {sm.errors} · предупреждений {sm.warnings} · замечаний модели {sm.model_flags} · проверок {len(sm.checks_run)}")
    tbl = Table(title="Замечания")
    tbl.add_column("слайд", justify="right")
    tbl.add_column("важность")
    tbl.add_column("проверка")
    tbl.add_column("что не так")
    tbl.add_column("исправление")
    for i in sorted(report.issues, key=lambda i: (i.slide, {"error": 0, "warn": 1, "info": 2}[i.severity])):
        tbl.add_row(str(i.slide), _SEVERITY_RU.get(i.severity, i.severity), i.check_id, i.message[:80], i.autofix.action if i.autofix else "")
    console.print(tbl)
    console.print(f"Отчёт: {target}")


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
    tbl = Table(title="Навыки")
    tbl.add_column("название")
    tbl.add_column("версия")
    tbl.add_column("роль")
    tbl.add_column("sha256")
    for name, spec in sorted(reg.skills.items()):
        tbl.add_row(name, spec.version, spec.role, spec.sha256[:12])
    console.print(tbl)


@app.command(name="checks")
def list_checks() -> None:
    """List audit checks (deterministic and model)."""
    from verstka.audit.model_checks import model_check_specs
    from verstka.audit.registry import all_checks

    tbl = Table(title="Проверки качества")
    tbl.add_column("id")
    tbl.add_column("вид")
    tbl.add_column("важность")
    tbl.add_column("группа")
    tbl.add_column("что проверяет")
    for spec, _ in all_checks():
        tbl.add_row(spec.id, spec.kind, _SEVERITY_RU.get(spec.severity, spec.severity), spec.category, spec.title)
    for spec in model_check_specs():
        tbl.add_row(spec.id, spec.kind, _SEVERITY_RU.get(spec.severity, spec.severity), spec.category, spec.title)
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
    # the service log shows each generation's steps with time stamps (plan, model calls, fallbacks, export)
    for h in logging.getLogger().handlers:
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
    if logging.getLogger("verstka").getEffectiveLevel() > logging.INFO:
        logging.getLogger("verstka").setLevel(logging.INFO)
    console.print(f"Verstka → http://{host}:{port}")
    uvicorn.run("verstka.api.app:app", host=host, port=port, reload=reload, log_level="info")
