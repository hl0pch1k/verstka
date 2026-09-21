"""render_deck: outline + layout plan + manifest → deck.pptx built on the template package."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from verstka.ingest.workspace import TemplateWorkspace
from verstka.rendering.clone import RenderedSlide, render_clone
from verstka.rendering.deck import DeckBuilder
from verstka.rendering.synth import render_synth
from verstka.schemas.layout import LayoutPlan, LayoutSlide
from verstka.schemas.outline import DeckOutline
from verstka.schemas.template import TemplateManifest

log = logging.getLogger(__name__)


@dataclass
class RenderResult:
    pptx_path: Path
    slides: list[RenderedSlide] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def warnings(self) -> list[str]:
        return [f"slide {s.index} ({s.outline_id}): {w}" for s in self.slides for w in s.warnings]


def _mark_notes(builder: DeckBuilder, oslide) -> None:
    """Write speaker notes plus a machine marker so the audit can map slides back to the outline."""
    try:
        slide = builder.created[-1]
        tf = slide.notes_slide.notes_text_frame
        base = (oslide.notes or "").strip()
        tf.text = (base + "\n" if base else "") + f"[verstka:{oslide.id}]"
    except Exception:  # noqa: BLE001
        pass


def render_deck(
    outline: DeckOutline,
    plan: LayoutPlan,
    manifest: TemplateManifest,
    ws: TemplateWorkspace,
    out_pptx: Path | str,
    progress: Optional[Callable[[str, float], None]] = None,
) -> RenderResult:
    t0 = time.time()
    builder = DeckBuilder(ws.source)
    patterns = {p.id: p for p in manifest.patterns}
    result = RenderResult(pptx_path=Path(out_pptx))
    n = len(outline.slides)
    for i, oslide in enumerate(outline.slides, 1):
        ps = plan.for_outline(oslide.id) or LayoutSlide(outline_id=oslide.id, mode="synth", composition="bullets", reasons=["no plan entry"])
        rendered = RenderedSlide(outline_id=oslide.id, index=i, mode=ps.mode, pattern_id=ps.pattern_id, composition=ps.composition)
        try:
            if ps.mode == "clone" and ps.pattern_id in patterns:
                _, warns = render_clone(builder, ps, oslide, patterns[ps.pattern_id], manifest, ws, outline)
            else:
                _, warns = render_synth(builder, ps, oslide, manifest, ws, outline)
            rendered.warnings.extend(warns)
        except Exception as e:  # noqa: BLE001
            log.exception("slide %d (%s) failed in mode %s", i, oslide.id, ps.mode)
            rendered.warnings.append(f"{ps.mode} failed: {str(e)[:160]}; fell back to synth")
            try:
                fallback = LayoutSlide(outline_id=oslide.id, mode="synth", composition=ps.composition or "bullets")
                _, warns = render_synth(builder, fallback, oslide, manifest, ws, outline)
                rendered.mode = "synth"
                rendered.warnings.extend(warns)
            except Exception as e2:  # noqa: BLE001
                log.exception("synth fallback failed for slide %d", i)
                rendered.warnings.append(f"synth fallback failed: {str(e2)[:160]}")
        _mark_notes(builder, oslide)
        result.slides.append(rendered)
        if progress:
            progress(f"rendered slide {i}/{n}", i / max(n, 1))
    builder.delete_original_slides()
    builder.save(out_pptx)
    result.seconds = round(time.time() - t0, 2)
    log.info("rendered %d slides to %s in %.1fs", len(result.slides), out_pptx, result.seconds)
    return result
