"""Autofix: turn audit issues into plan/outline changes and XML edits, re-render, re-audit (≤ 2 iterations, rollback on regression)."""

from __future__ import annotations

import copy
import logging
import shutil
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
from verstka.rendering.deck import element_bbox, is_nested, set_element_pos, slide_shape_elements
from verstka.rendering.renderer import RenderResult, render_deck
from verstka.schemas.audit import AuditReport, FixAction, Issue
from verstka.schemas.common import Bbox
from verstka.schemas.layout import LayoutPlan
from verstka.schemas.outline import DeckOutline
from verstka.schemas.template import TemplateManifest
from verstka.skills_registry.registry import SkillsRegistry

log = logging.getLogger(__name__)

STRUCTURAL_ACTIONS = ("rematch", "synth")  # need a full re-render of the slide
RERENDER_ACTIONS = STRUCTURAL_ACTIONS + ("condense_text",)
MIN_FONT_PT = 8.0  # body text below this is unreadable on a projector; footnote sizes of the scale are not shrink targets


def plan_fixes(report: AuditReport, plan: LayoutPlan, only_ids: Optional[set[str]] = None, *, xml_only: bool = False) -> dict[str, list[FixAction]]:
    """outline_id → actions (at most one structural action per slide, plus text/colour actions).

    Info-level findings are advisory and never fixed unless the caller asked for them by issue id.
    With xml_only, only in-place XML edits are returned (used to re-derive fixes after a re-render)."""
    by_slide: dict[str, list[FixAction]] = {}
    for issue in report.issues:
        if only_ids is not None and issue.id not in only_ids:
            continue
        if not issue.autofix or issue.kind == "model" or issue.autofix.action == "none":
            continue
        if issue.severity == "info" and only_ids is None:
            continue
        if xml_only and issue.autofix.action in RERENDER_ACTIONS:
            continue
        oid = issue.outline_id or issue.autofix.params.get("outline_id")
        if not oid:
            continue
        by_slide.setdefault(oid, []).append(issue.autofix)
    # collapse: one structural action per slide; a re-render supersedes geometry/size edits of the same slide
    out: dict[str, list[FixAction]] = {}
    for oid, actions in by_slide.items():
        structural = [a for a in actions if a.action in STRUCTURAL_ACTIONS]
        others = [a for a in actions if a.action not in STRUCTURAL_ACTIONS]
        chosen: list[FixAction] = []
        if structural:
            chosen.append(structural[0])
            others = [a for a in others if a.action not in ("shrink_text", "move_inside")]
        chosen.extend(others)
        if chosen:
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


# ----------------------------------------------------------------------------- XML edits


def _snap_size(size_pt: float, factor: float, scale: list[float]) -> float:
    """Next smaller step of the template's type scale that is ≤ size·factor, so the result stays in scale.

    With no step small enough, the smallest step below the current size is used (a partial shrink is still in scale);
    below the scale's floor the raw target is used only while it stays within 2 pt of a scale step (audit: info, not warn),
    otherwise the size is left alone — an out-of-scale 6 pt run is worse than the overflow it tries to hide."""
    target = size_pt * factor
    lower = sorted((s for s in scale if MIN_FONT_PT <= s < size_pt - 0.25), reverse=True)
    for s in lower:
        if s <= target + 0.25:
            return max(s, MIN_FONT_PT)
    if lower:
        return max(lower[-1], MIN_FONT_PT)
    raw = max(round(target * 2) / 2, MIN_FONT_PT)
    if not scale or any(abs(raw - s) <= 2.0 for s in scale):
        return raw
    return size_pt


def _force_run_color(rPr: etree._Element, hex_: str) -> int:
    """Give a run an explicit solid colour when its colour is inherited or a scheme colour. Returns 1 if changed."""
    fill = rPr.find(q("a:solidFill"))
    if fill is not None:
        if fill.find(q("a:srgbClr")) is not None:
            return 0  # handled by the srgbClr pass
        for child in list(fill):
            fill.remove(child)
        etree.SubElement(fill, q("a:srgbClr")).set("val", hex_)
        return 1
    if any(rPr.find(q(t)) is not None for t in ("a:noFill", "a:gradFill", "a:pattFill", "a:blipFill", "a:grpFill")):
        return 0
    fill = etree.Element(q("a:solidFill"))
    etree.SubElement(fill, q("a:srgbClr")).set("val", hex_)
    ln = rPr.find(q("a:ln"))
    rPr.insert(rPr.index(ln) + 1 if ln is not None else 0, fill)  # schema order: ln, fill, effects, …, latin
    return 1


def _recolor(el: etree._Element, scope: str, only_hex: Optional[str], target_hex: Optional[str], palette: list[str]) -> int:
    """Replace colours inside el. scope='text' touches p:txBody only (runs, bullets); 'all' also the shape fill/outline."""
    roots = list(el.iter(q("p:txBody"))) if scope == "text" else [el]
    changed = 0
    for root in roots:
        for clr in list(root.iter(q("a:srgbClr"))):
            val = (clr.get("val") or "").upper()
            if only_hex and val != only_hex:
                continue
            new_hex = target_hex or (nearest_palette_color(val, palette)[0] if palette and val else None)
            if new_hex and new_hex.upper() != val:
                clr.set("val", new_hex.upper())
                changed += 1
        if scope == "text" and target_hex and not only_hex:
            for rPr in root.iter(q("a:rPr")):  # inherited/scheme colours become explicit so the fix is visible
                changed += _force_run_color(rPr, target_hex.upper())
    return changed


def _move_inside(el: etree._Element, safe: Bbox, slide_w: int, slide_h: int, into_safe: bool) -> Optional[tuple[int, int, int, int]]:
    """New (x, y, w, h) that puts el inside the slide (or the safe area); oversized elements are shrunk to fit. None = no change."""
    if is_nested(el):
        return None  # group children use group coordinates
    box = element_bbox(el)
    if not box:
        return None
    x, y, w, h = box
    bx, by, bw, bh = (safe.x, safe.y, safe.w, safe.h) if into_safe else (0, 0, slide_w, slide_h)
    nw, nh, nx, ny = w, h, x, y
    if w > bw:
        nw = bw if into_safe else max(slide_w - 2 * safe.x, 1)
        nx = bx if into_safe else safe.x
    else:
        nx = min(max(x, bx), bx + bw - w)
    if h > bh:
        nh = bh if into_safe else max(slide_h - 2 * safe.y, 1)
        ny = by if into_safe else safe.y
    else:
        ny = min(max(y, by), by + bh - h)
    if (nx, ny, nw, nh) == (x, y, w, h):
        return None
    return nx, ny, nw, nh


def _xml_fixes(pptx: Path, actions: list[tuple[int, FixAction]], manifest: TemplateManifest, slide_w: int, slide_h: int) -> list[str]:
    """In-place edits that need no re-render: recolor, refont, drop_element, move_inside, shrink_text. Returns what changed."""
    if not actions:
        return []
    prs = Presentation(str(pptx))
    applied: list[str] = []
    palette = manifest.tokens.palette()
    primary_font = manifest.tokens.typography.primary_family
    text_primary = manifest.tokens.color_for("text.primary")
    typo = manifest.tokens.typography
    scale = sorted({float(s) for s in (typo.sizes_used or [st.size_pt for st in typo.scale])})
    safe = manifest.tokens.spacing.safe_area.to_emu(slide_w, slide_h)
    for slide_index, act in actions:
        if not (1 <= slide_index <= len(prs.slides)):
            continue
        by_id = slide_shape_elements(prs.slides[slide_index - 1])
        ids = act.params.get("element_ids") or ([act.params["element_id"]] if act.params.get("element_id") else [])
        for eid in ids:
            el = by_id.get(str(eid))
            if el is None:
                continue
            if act.action == "drop_element":
                el.getparent().remove(el)
                applied.append(f"slide {slide_index}: removed {eid}")
            elif act.action == "refont" and primary_font:
                n = 0
                for latin in el.iter(q("a:latin")):
                    if latin.get("typeface") != primary_font:
                        latin.set("typeface", primary_font)
                        n += 1
                for rPr in el.iter(q("a:rPr")):
                    if rPr.find(q("a:latin")) is None:
                        etree.SubElement(rPr, q("a:latin")).set("typeface", primary_font)
                        n += 1
                if n:
                    applied.append(f"slide {slide_index}: font → {primary_font} in {eid} ({n} runs)")
            elif act.action == "recolor":
                target_hex = (act.params.get("to") or "").upper() or None
                if not target_hex and act.params.get("target") == "text.primary" and text_primary:
                    target_hex = text_primary.upper()
                only_hex = (act.params.get("hex") or "").upper() or None
                scope = act.params.get("scope") or "text"
                n = _recolor(el, scope, only_hex, target_hex, palette)
                if n:
                    applied.append(f"slide {slide_index}: recolored {n} colour(s) in {eid} → {target_hex or 'палитра'} ({scope})")
            elif act.action == "move_inside":
                moved = _move_inside(el, safe, slide_w, slide_h, bool(act.params.get("safe")))
                if moved:
                    x, y, w, h = element_bbox(el)  # type: ignore[misc]
                    nx, ny, nw, nh = moved
                    set_element_pos(el, x=nx, y=ny, w=nw if nw != w else None, h=nh if nh != h else None)
                    where = "в безопасную область" if act.params.get("safe") else "внутрь слайда"
                    resized = f", размер {nw}×{nh}" if (nw, nh) != (w, h) else ""
                    applied.append(f"slide {slide_index}: moved {eid} {where}{resized}")
            elif act.action == "shrink_text":
                ratio = float(act.params.get("ratio", 1.2))
                factor = max(0.6, min(0.95, 1 / ratio))
                sizes: list[float] = []
                for rPr in el.iter(q("a:rPr")):
                    sz = rPr.get("sz")
                    if not sz:
                        continue
                    cur = int(sz) / 100.0
                    new = _snap_size(cur, factor, scale)
                    if new < cur:
                        rPr.set("sz", str(int(round(new * 100))))
                        sizes.append(new)
                if sizes:
                    applied.append(f"slide {slide_index}: shrunk text in {eid} to {', '.join(f'{s:g}' for s in sorted(set(sizes), reverse=True))} pt")
    if applied:
        prs.save(str(pptx))
    return applied


# ----------------------------------------------------------------------------- loop


class _Snapshot:
    """deck.pptx + plan + outline + render result before an iteration, to undo it when the audit gets worse."""

    def __init__(self, pptx: Path, plan: LayoutPlan, outline: DeckOutline, render_result: RenderResult | None, iteration: int):
        self.bak = pptx.with_name(f"{pptx.stem}.iter{iteration}.bak")
        self.had_file = pptx.exists()
        if self.had_file:
            shutil.copy2(pptx, self.bak)
        self.plan = copy.deepcopy(plan)
        self.outline = copy.deepcopy(outline)
        self.render_result = render_result

    def restore(self, pptx: Path) -> tuple[LayoutPlan, DeckOutline, RenderResult | None]:
        if self.had_file and self.bak.exists():
            shutil.copy2(self.bak, pptx)
        return self.plan, self.outline, self.render_result

    def discard(self) -> None:
        try:
            self.bak.unlink(missing_ok=True)
        except OSError:
            pass


def _better(new: AuditReport, old: AuditReport) -> bool:
    """Fewer errors, then fewer warnings, then a higher score."""
    return (new.summary.errors, new.summary.warnings, -new.summary.score) < (old.summary.errors, old.summary.warnings, -old.summary.score)


def _issue_key(i: Issue) -> tuple:
    return (i.check_id, i.outline_id or i.slide)


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
    """Apply fixes while the audit improves; an iteration that makes it worse is rolled back (deck, plan, outline).

    Returns the final report/plan/outline (and last render)."""
    pptx = Path(pptx)
    current = report
    render_result: RenderResult | None = None
    slide_w, slide_h = manifest.slide_size.w, manifest.slide_size.h
    audit_kw = dict(providers=providers if use_models else None, skills=skills if use_models else None, use_vlm=use_models, use_llm=use_models, images_dir=images_dir, strategy=report.strategy)
    selected_keys = {_issue_key(i) for i in current.issues if i.id in only_ids} if only_ids is not None else None
    for it in range(1, max_iterations + 1):
        fixes = plan_fixes(current, plan, only_ids)
        if not fixes:
            break
        snapshot = _Snapshot(pptx, plan, outline, render_result, it)
        try:
            applied: list[dict] = []
            need_render = False
            xml_actions: list[tuple[int, FixAction]] = []
            slide_index_of = {s.outline_id: s.index for s in _ir_slides(current)}
            for oid, actions in fixes.items():
                for act in actions:
                    if act.action in STRUCTURAL_ACTIONS:
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
                # element ids change after a re-render: re-derive the XML fixes from a render-free audit of the new deck
                fresh = run_audit(pptx, manifest, outline, ws, render=False, images_dir=images_dir, strategy=report.strategy)
                fresh_ids = {i.id for i in fresh.issues if _issue_key(i) in selected_keys} if selected_keys is not None else None
                fresh_index_of = {s.outline_id: s.index for s in _ir_slides(fresh)}
                xml_actions = []
                for oid, actions in plan_fixes(fresh, plan, fresh_ids, xml_only=True).items():
                    idx = fresh_index_of.get(oid)
                    if idx:
                        xml_actions.extend((idx, a) for a in actions)
            if xml_actions:
                for line in _xml_fixes(pptx, xml_actions, manifest, slide_w, slide_h):
                    applied.append({"iteration": it, "action": "xml", "result": line})
            if not applied:
                break
            new_report = run_audit(pptx, manifest, outline, ws, **audit_kw)
            new_report.applied_fixes = current.applied_fixes + applied
            new_report.iterations = it
            if _better(new_report, current):
                current = new_report
                continue
            # the iteration made things worse: ship the previous deck, re-audit it so slide images match
            plan, outline, render_result = snapshot.restore(pptx)
            restored = run_audit(pptx, manifest, outline, ws, **audit_kw)
            rollback = {"iteration": it, "action": "rollback", "result": f"ошибок было {current.summary.errors}, стало {new_report.summary.errors} (предупреждений {current.summary.warnings} → {new_report.summary.warnings}, оценка {current.summary.score} → {new_report.summary.score}) — откат"}
            log.info("autofix iteration %d rolled back: %s", it, rollback["result"])
            restored.applied_fixes = current.applied_fixes + applied + [rollback]
            restored.iterations = it
            current = restored
            break
        finally:
            snapshot.discard()
    return current, plan, outline, render_result


def _ir_slides(report: AuditReport):
    from verstka.audit.ir import build_deck_ir

    try:
        return build_deck_ir(report.deck, with_images=False).slides
    except Exception:  # noqa: BLE001
        return []
