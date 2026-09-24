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


def _snapshot(builder: DeckBuilder) -> tuple[int, set[str]]:
    return len(builder.created), {sld.get("id") for sld in builder.prs.slides._sldIdLst}


def _rollback(builder: DeckBuilder, snapshot: tuple[int, set[str]]) -> int:
    """Drop every slide a failed renderer added after the snapshot; returns how many were removed."""
    n_created, ids = snapshot
    sld_lst = builder.prs.slides._sldIdLst
    removed = 0
    for sld in list(sld_lst):
        if sld.get("id") not in ids:
            rid = sld.rId
            sld_lst.remove(sld)
            try:
                builder.prs.part.drop_rel(rid)
            except KeyError:
                pass
            removed += 1
    del builder.created[n_created:]
    return removed


def _give_geometry(builder: DeckBuilder) -> None:
    """Every shape that is not a placeholder carries its own geometry: a box cut loose from a layout placeholder
    would otherwise be a shape of no known kind to PowerPoint's object model and to python-pptx."""
    from lxml import etree

    from verstka.analysis.xmlns import q

    for slide in builder.created:
        for sp in slide._element.iter(q("p:sp")):
            if sp.find(".//" + q("p:ph")) is not None:
                continue
            spPr = sp.find(q("p:spPr"))
            if spPr is None or spPr.find(q("a:prstGeom")) is not None or spPr.find(q("a:custGeom")) is not None:
                continue
            geom = etree.Element(q("a:prstGeom"))
            geom.set("prst", "rect")
            etree.SubElement(geom, q("a:avLst"))
            xfrm = spPr.find(q("a:xfrm"))
            if xfrm is not None:
                xfrm.addnext(geom)
            else:
                spPr.insert(0, geom)


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
        before = _snapshot(builder)
        try:
            if ps.mode == "clone" and ps.pattern_id in patterns:
                _, warns = render_clone(builder, ps, oslide, patterns[ps.pattern_id], manifest, ws, outline)
            else:
                _, warns = render_synth(builder, ps, oslide, manifest, ws, outline)
            rendered.warnings.extend(warns)
        except Exception as e:  # noqa: BLE001
            log.exception("slide %d (%s) failed in mode %s", i, oslide.id, ps.mode)
            rendered.warnings.append(f"{ps.mode} failed: {str(e)[:160]}; fell back to synth")
            # a half-filled clone must not stay in the deck next to its synth replacement
            _rollback(builder, before)
            try:
                fallback = LayoutSlide(outline_id=oslide.id, mode="synth", composition=ps.composition or "bullets")
                _, warns = render_synth(builder, fallback, oslide, manifest, ws, outline)
                rendered.mode = "synth"
                rendered.warnings.extend(warns)
            except Exception as e2:  # noqa: BLE001
                log.exception("synth fallback failed for slide %d", i)
                rendered.warnings.append(f"synth fallback failed: {str(e2)[:160]}")
                _rollback(builder, before)
        if len(builder.created) > before[0]:
            _mark_notes(builder, oslide)  # only a slide made for this outline entry carries its marker
        result.slides.append(rendered)
        if progress:
            progress(f"rendered slide {i}/{n}", i / max(n, 1))
    builder.delete_original_slides()
    _give_geometry(builder)
    builder.save(out_pptx)
    result.seconds = round(time.time() - t0, 2)
    log.info("rendered %d slides to %s in %.1fs", len(result.slides), out_pptx, result.seconds)
    return result
