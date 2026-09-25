"""run_audit: DeckIR → deterministic checks → optional model checks → AuditReport."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from verstka.audit.ir import build_deck_ir
from verstka.audit.registry import AuditContext, run_checks
from verstka.ingest.render import RenderError, find_pdftoppm, find_soffice, render_slides
from verstka.ingest.workspace import TemplateWorkspace
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.audit import AuditReport
from verstka.schemas.outline import DeckOutline
from verstka.schemas.template import TemplateManifest
from verstka.skills_registry.registry import SkillsRegistry

log = logging.getLogger(__name__)


def run_audit(
    pptx: Path | str,
    manifest: TemplateManifest,
    outline: Optional[DeckOutline] = None,
    ws: Optional[TemplateWorkspace] = None,
    *,
    providers: Optional[ProviderRegistry] = None,
    skills: Optional[SkillsRegistry] = None,
    use_vlm: bool = True,
    use_llm: bool = True,
    render: bool = True,
    images_dir: Optional[Path] = None,
    existing_images: Optional[dict[int, Path]] = None,
    strategy: Optional[str] = None,
    brief_text: Optional[str] = None,
) -> AuditReport:
    t0 = time.time()
    pptx = Path(pptx)
    report = AuditReport(deck=str(pptx), template_id=manifest.template_id, strategy=strategy)
    opens_ok = True
    try:
        ir = build_deck_ir(pptx)
    except Exception as e:  # noqa: BLE001
        log.exception("deck does not open")
        from verstka.schemas.deck_ir import DeckIR

        ir = DeckIR(source=str(pptx), slide_w=manifest.slide_size.w, slide_h=manifest.slide_size.h)
        opens_ok = False
        report.issues.append(__import__("verstka.schemas.audit", fromlist=["Issue"]).Issue(id="file_opens-0-0", slide=0, check_id="file_opens", severity="error", kind="deterministic", message=f"файл не открывается: {str(e)[:120]}"))
    images: dict[int, Path] = dict(existing_images or {})
    render_ok: Optional[bool] = None
    if render and not images and find_soffice() and find_pdftoppm():
        try:
            paths = render_slides(pptx, images_dir or pptx.parent / "slides", dpi=110)
            images = {i + 1: p for i, p in enumerate(paths)}
            render_ok = True
        except RenderError as e:
            render_ok = False
            log.warning("render failed: %s", e)
    elif images:
        render_ok = True
    ctx = AuditContext(ir=ir, manifest=manifest, outline=outline, ws=ws, slide_images=images, render_ok=render_ok, opens_ok=opens_ok, brief_text=brief_text)
    if opens_ok:
        issues, ran = run_checks(ctx)
        report.issues.extend(issues)
        report.summary.checks_run = ran
        report.summary.figures = ctx.figure_stats
        if providers is not None and skills is not None and (use_vlm or use_llm):
            from verstka.audit.model_checks import run_model_checks

            m_issues, warns = run_model_checks(ctx, skills, providers, use_vlm=use_vlm and bool(images), use_llm=use_llm)
            report.issues.extend(m_issues)
            for w in warns:
                log.info(w)
    report.slide_images = {i: str(p) for i, p in images.items()}
    report.recompute()
    report.seconds = round(time.time() - t0, 2)
    return report
