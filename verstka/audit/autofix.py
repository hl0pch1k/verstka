"""Autofix: turn audit issues into plan/outline changes and XML edits, re-render, re-audit (≤ 2 iterations)."""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Optional

from lxml import etree
from pptx import Presentation

from verstka.analysis.colors import nearest_palette_color
from verstka.analysis.xmlns import q
from verstka.audit.runner import run_audit
from verstka.ingest.workspace import TemplateWorkspace
from verstka.matching.compat import composition_for
from verstka.planning.condense import trim_words
from verstka.providers.registry import ProviderRegistry
from verstka.rendering.deck import element_bbox, set_element_pos
from verstka.rendering.renderer import RenderResult, render_deck
from verstka.schemas.audit import AuditReport, FixAction, Issue
from verstka.schemas.layout import LayoutPlan, LayoutSlide
from verstka.schemas.outline import DeckOutline
from verstka.schemas.template import TemplateManifest
from verstka.skills_registry.registry import SkillsRegistry

log = logging.getLogger(__name__)

# which issue classes trigger a re-render of the slide with a different pattern
REMATCH_CHECKS = {"overlap", "text_clipped", "empty_slide", "out_of_bounds"}
SEVERE_OVERFLOW = 1.5


def plan_fixes(report: AuditReport, plan: LayoutPlan, only_ids: Optional[set[str]] = None) -> dict[str, list[FixAction]]:
    """outline_id → actions (at most one structural action per slide, plus text/colour actions)."""
    by_slide: dict[str, list[FixAction]] = {}
    for issue in report.issues:
        if only_ids is not None and issue.id not in only_ids:
            continue
        if not issue.autofix or issue.kind == "model":
            continue
        oid = issue.outline_id or issue.autofix.params.get("outline_id")
        if not oid:
            continue
        actions = by_slide.setdefault(oid, [])
        act = issue.autofix
        if issue.check_id == "text_overflow" and issue.details.get("ratio", 0) >= SEVERE_OVERFLOW:
            act = FixAction(action="rematch", params={"outline_id": oid}, description="сильное переполнение: перевыбрать макет")
        actions.append(act)
    # collapse: one structural action per slide
    out: dict[str, list[FixAction]] = {}
    for oid, actions in by_slide.items():
        structural = [a for a in actions if a.action in ("rematch", "synth")]
        others = [a for a in actions if a.action not in ("rematch", "synth")]
        chosen: list[FixAction] = []
        if structural:
            chosen.append(structural[0])
            others = [a for a in others if a.action not in ("shrink_text", "move_inside")]  # re-render supersedes these
        chosen.extend(others)
        out[oid] = chosen
    return out


def _rematch(plan: LayoutPlan, outline: DeckOutline, oid: str) -> str:
    ps = plan.for_outline(oid)
    osl = next((s for s in outline.slides if s.id == oid), None)
    if ps is None or osl is None:
        return "skip"
    tried = set(ps.fit.get("tried", []))
    if ps.pattern_id:
        tried.add(ps.pattern_id)
    for pid, score in ps.alternatives:
        if pid not in tried and score >= 0.3:
            ps.mode = "clone"
            ps.pattern_id = pid
            ps.fit["tried"] = sorted(tried)
            ps.reasons.append(f"автофикс: перевыбран паттерн {pid} ({score:.2f})")
            return f"rematch → {pid}"
    if ps.mode != "synth":
        ps.mode = "synth"
        ps.pattern_id = None
        ps.composition = composition_for(osl)
        ps.fit["tried"] = sorted(tried)
        ps.reasons.append(f"автофикс: синтез композиции {ps.composition}")
        return f"synth → {ps.composition}"
    return "skip"


def _condense(outline: DeckOutline, oid: str, skills: Optional[SkillsRegistry], providers: Optional[ProviderRegistry]) -> str:
    from verstka.planning.condense import condense_text

    osl = next((s for s in outline.slides if s.id == oid), None)
    if osl is None:
        return "skip"
    c = osl.content
    changed = 0
    new_bullets = []
    for b in c.bullets[:6]:
        nb = condense_text(b, 15, skills, providers, outline.language)
        changed += nb != b
        new_bullets.append(nb)
    changed += len(c.bullets) > 6
    c.bullets = new_bullets
    for it in c.items + c.columns:
        if it.text and len(it.text.split()) > 24:
            it.text = condense_text(it.text, 24, skills, providers, outline.language)
            changed += 1
        it.bullets = [condense_text(b, 15, skills, providers, outline.language) for b in it.bullets[:6]]
    for p_i, p in enumerate(c.paragraphs):
        if len(p.split()) > 60:
            c.paragraphs[p_i] = trim_words(p, 60)
            changed += 1
    return f"condensed {changed} texts" if changed else "skip"


def _xml_fixes(pptx: Path, actions: list[tuple[int, FixAction]], manifest: TemplateManifest, slide_w: int, slide_h: int) -> list[str]:
    """In-place edits that need no re-render: recolor, refont, drop_element, move_inside, shrink_text."""
    if not actions:
        return []
    prs = Presentation(str(pptx))
    applied: list[str] = []
    palette = manifest.tokens.palette()
    primary_font = manifest.tokens.typography.primary_family
    text_primary = manifest.tokens.color_for("text.primary")
    for slide_index, act in actions:
        if not (1 <= slide_index <= len(prs.slides)):
            continue
        slide = prs.slides[slide_index - 1]
        tree = slide._element.cSld.find(q("p:spTree"))
        by_id = {}
        for nv in tree.iter(q("p:cNvPr")):
            d = nv.getparent().getparent()
            if d is not None and etree.QName(d).localname != "spTree":
                by_id[nv.get("id")] = d
        ids = act.params.get("element_ids") or ([act.params["element_id"]] if act.params.get("element_id") else [])
        for eid in ids:
            el = by_id.get(str(eid))
            if el is None:
                continue
            if act.action == "drop_element":
                el.getparent().remove(el)
                applied.append(f"slide {slide_index}: removed {eid}")
            elif act.action == "refont" and primary_font:
                for latin in el.iter(q("a:latin")):
                    latin.set("typeface", primary_font)
                for rPr in el.iter(q("a:rPr")):
                    if rPr.find(q("a:latin")) is None:
                        lat = etree.SubElement(rPr, q("a:latin"))
                        lat.set("typeface", primary_font)
                applied.append(f"slide {slide_index}: font → {primary_font} in {eid}")
            elif act.action == "recolor":
                target_hex = None
                if act.params.get("target") == "text.primary" and text_primary:
                    target_hex = text_primary
                for clr in el.iter(q("a:srgbClr")):
                    val = (clr.get("val") or "").upper()
                    if act.params.get("hex") and val != act.params["hex"].upper():
                        continue
                    new_hex = target_hex or (nearest_palette_color(val, palette)[0] if palette and val else None)
                    if new_hex and new_hex != val:
                        clr.set("val", new_hex)
                applied.append(f"slide {slide_index}: recolored {eid}")
            elif act.action == "move_inside":
                box = element_bbox(el)
                if box:
                    x, y, w, h = box
                    nx = min(max(x, 0), max(slide_w - w, 0))
                    ny = min(max(y, 0), max(slide_h - h, 0))
                    if (nx, ny) != (x, y):
                        set_element_pos(el, x=nx, y=ny)
                        applied.append(f"slide {slide_index}: moved {eid} inside")
            elif act.action == "shrink_text":
                ratio = float(act.params.get("ratio", 1.2))
                factor = max(0.6, min(0.95, 1 / ratio))
                for rPr in el.iter(q("a:rPr")):
                    sz = rPr.get("sz")
                    if sz:
                        rPr.set("sz", str(max(int(int(sz) * factor), 600)))
                applied.append(f"slide {slide_index}: shrunk text in {eid} ×{factor:.2f}")
    prs.save(str(pptx))
    return applied


def autofix_loop(
    pptx: Path,
    report: AuditReport,
    outline: DeckOutline,
    plan: LayoutPlan,
    manifest: TemplateManifest,
    ws: TemplateWorkspace,
    *,
    providers: Optional[ProviderRegistry] = None,
    skills: Optional[SkillsRegistry] = None,
    max_iterations: int = 2,
    use_models: bool = False,
    only_ids: Optional[set[str]] = None,
    images_dir: Optional[Path] = None,
) -> tuple[AuditReport, LayoutPlan, DeckOutline, RenderResult | None]:
    """Apply fixes while the error count decreases. Returns the final report/plan/outline (and last render)."""
    current = report
    render_result: RenderResult | None = None
    for it in range(1, max_iterations + 1):
        fixes = plan_fixes(current, plan, only_ids)
        if not fixes:
            break
        applied: list[dict] = []
        need_render = False
        xml_actions: list[tuple[int, FixAction]] = []
        slide_index_of = {s.outline_id: s.index for s in _ir_slides(current)}
        for oid, actions in fixes.items():
            for act in actions:
                if act.action in ("rematch", "synth"):
                    res = _rematch(plan, outline, oid)
                    applied.append({"iteration": it, "outline_id": oid, "action": act.action, "result": res})
                    need_render = need_render or res != "skip"
                elif act.action == "condense_text":
                    res = _condense(outline, oid, skills if use_models else None, providers if use_models else None)
                    applied.append({"iteration": it, "outline_id": oid, "action": act.action, "result": res})
                    need_render = need_render or res != "skip"
                else:
                    idx = slide_index_of.get(oid)
                    if idx:
                        xml_actions.append((idx, act))
        if need_render:
            render_result = render_deck(outline, plan, manifest, ws, pptx)
            # element ids may change after a re-render: XML fixes are re-derived on the next audit
            xml_actions = [a for a in xml_actions if a[1].action in ()]
        if xml_actions:
            for line in _xml_fixes(pptx, xml_actions, manifest, manifest.slide_size.w, manifest.slide_size.h):
                applied.append({"iteration": it, "action": "xml", "result": line})
        if not applied:
            break
        new_report = run_audit(pptx, manifest, outline, ws, providers=providers if use_models else None, skills=skills if use_models else None, use_vlm=use_models, use_llm=use_models, images_dir=images_dir, strategy=current.strategy)
        new_report.applied_fixes = current.applied_fixes + applied
        new_report.iterations = it
        improved = new_report.summary.errors < current.summary.errors or (new_report.summary.errors == current.summary.errors and new_report.summary.warnings < current.summary.warnings)
        current = new_report
        if not improved:
            break
    return current, plan, outline, render_result


def _ir_slides(report: AuditReport):
    from verstka.audit.ir import build_deck_ir

    try:
        return build_deck_ir(report.deck, with_images=False).slides
    except Exception:  # noqa: BLE001
        return []
