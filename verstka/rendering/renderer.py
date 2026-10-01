"""render_deck: outline + layout plan + manifest → deck.pptx built on the template package."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from verstka.ingest.workspace import TemplateWorkspace
from verstka.rendering.clone import KEPT_PHOTO, RenderedSlide, render_clone
from verstka.rendering.deck import DeckBuilder
from verstka.rendering.fallbacks import fallback_composition, prepare_slide
from verstka.rendering.synth import render_synth
from verstka.ru import deck_typography
from verstka.schemas.layout import LayoutPlan, LayoutSlide
from verstka.schemas.outline import DeckOutline
from verstka.schemas.template import TemplateManifest

log = logging.getLogger(__name__)


@dataclass
class RenderResult:
    pptx_path: Path
    slides: list[RenderedSlide] = field(default_factory=list)
    seconds: float = 0.0
    # (outline id, sample id) of the template samples that read badly on a slide (`clone_check.content_trouble`):
    # the deck's samples are chosen again without them (pipeline/generate.py)
    failed_samples: set[tuple[str, str]] = field(default_factory=set)

    @property
    def clones(self) -> list[str]:
        """The samples the deck's content slides stand on, in order (covers, dividers and closing slides aside)."""
        return [s.pattern_id for s in self.slides if s.mode == "clone" and s.pattern_id]

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
    skip: Optional[set] = None,
) -> RenderResult:
    """`skip`: (outline id, sample id) pairs an earlier render of this deck found reading badly — not tried again."""
    # one percent style for the whole deck — the style of its own words (G5-16: never «42 %» and «42%» on one slide);
    # Russian text in a template family without Cyrillic is measured and set in a stand-in (cyrillic.py)
    from verstka.rendering.cyrillic import apply_to_pptx, cyrillic_substitutes, deck_fonts, mark_russian, strip_highlights

    try:
        subs = cyrillic_substitutes(ws.source, extra=[f.family for f in manifest.tokens.typography.families])
    except Exception:  # noqa: BLE001 - the template's own families then
        subs = {}
    with deck_typography([outline.model_dump_json()]), deck_fonts(subs):
        result = _render_deck(outline, plan, manifest, ws, out_pptx, progress, skip=skip)
    if subs:
        try:
            if apply_to_pptx(out_pptx, subs):
                log.info("Russian text set in stand-ins of the template's families without Cyrillic: %s", ", ".join(f"{k} → {v}" for k, v in subs.items()))
        except Exception:  # noqa: BLE001 - the deck stays as rendered
            log.warning("cyrillic stand-ins not written", exc_info=True)
    try:
        mark_russian(out_pptx)
        strip_highlights(out_pptx)
    except Exception:  # noqa: BLE001 - the deck stays as rendered
        log.warning("Russian runs not tagged ru-RU / highlights not taken off", exc_info=True)
    return result


class _CoverRedo(RuntimeError):
    """A cloned cover that reads badly: the slide is rolled back and composed."""


class _CloneRedo(RuntimeError):
    """No template sample holds a content slide well: the slide is rolled back and composed."""


_BOOKEND_VALUES = ("title", "section", "thanks")
ALT_MAX = 4  # template samples tried for a content slide before it is composed


def _render_content_clone(builder: DeckBuilder, ps: LayoutSlide, oslide, patterns: dict, manifest: TemplateManifest, ws: TemplateWorkspace, outline: DeckOutline, used: dict, before, failed: Optional[set] = None, skip: Optional[set] = None) -> tuple:
    """A content slide on its template sample, checked (`clone_check.content_trouble`); a sample that loses content or
    reads badly is rolled back and the next one of the plan's alternatives not used elsewhere in the deck is tried.
    `failed` collects (outline id, sample id) of the samples that read badly; `skip`: pairs known to read badly from
    an earlier render of the deck, not tried again. Raises _CloneRedo when none holds the slide."""
    from verstka.rendering.clone_check import content_trouble

    tried: list[str] = []
    skip = skip or set()
    # (an alternative scored far below the slide's own choice — a tile grid whose numerals stay on empty tiles — is no
    # better than the composed slide)
    # (an alternative that holds the slide well on its own — 0.6 and more — is tried whatever the first one scored: a
    # sample of the template's art scored 1.1 must not shut out a 0.8 one when it reads badly)
    floor_sc = max(0.45, min((ps.score or 0.0) - 0.3, 0.6))
    order = [ps.pattern_id] + [pid for pid, sc in (ps.alternatives or []) if pid != ps.pattern_id and used.get(pid, 0) == 0 and (sc or 0.0) >= floor_sc]
    order = [pid for pid in order if (oslide.id, pid) not in skip]
    for pid in order[:ALT_MAX]:
        p = patterns.get(pid)
        if p is None or p.kind.value in _BOOKEND_VALUES:
            continue
        slide, warns = render_clone(builder, ps, oslide, p, manifest, ws, outline)
        from verstka.rendering.clone_notes import place_lede, place_notes

        place_lede(builder, slide, oslide, outline, manifest, p, warns)
        why = place_notes(builder, slide, oslide, outline, manifest, p) or content_trouble(slide, oslide, p, manifest, warns)
        if why is None:
            if pid != ps.pattern_id:
                ps.reasons = [f"слайд {p.source_slide} шаблона: первый выбранный образец не вместил содержимое"] + [r for r in ps.reasons if not r.startswith("слайд ")]
                ps.pattern_id = pid
            return slide, warns + [f"sample {t} read badly — next sample" for t in tried]
        tried.append(f"{pid} ({why[:80]})")
        if failed is not None:
            failed.add((oslide.id, pid))
        _rollback(builder, before)
    raise _CloneRedo("; ".join(tried) or "no sample")


def _bookend_trouble(slide, oslide: DeckOutline) -> Optional[str]:
    """Why a cloned cover, divider or closing slide reads badly, or None: a word of its heading wider than the
    heading's box at the size it was set (the renderer breaks it), or two of its texts laid over each other."""
    from verstka.rendering.fonts import text_width_pt
    from verstka.schemas.common import EMU_PER_PT

    kind = getattr(getattr(oslide, "kind", None), "value", str(getattr(oslide, "kind", "")))
    if kind not in ("title", "section", "thanks") or slide is None:
        return None
    boxes = []
    for sh in slide.shapes:
        if not sh.has_text_frame or not sh.text_frame.text.strip() or sh.width is None or sh.left is None or sh.top is None or sh.height is None:
            continue
        boxes.append(sh)
    try:
        prs = slide.part.package.presentation_part.presentation
        W, H = int(prs.slide_width), int(prs.slide_height)
    except Exception:  # noqa: BLE001
        W = H = 0
    if W and H:
        for sh in boxes:
            if sh.top + sh.height > H * 1.02 or sh.left + sh.width > W * 1.02 or sh.top < -0.02 * H or sh.left < -0.02 * W or sh.height <= 0:
                return "sets a line of text off the slide"
    head = (oslide.headline or "").strip()
    for sh in boxes:
        text = sh.text_frame.text.replace("\x0b", " ").replace("\n", " ")
        if not head or head.split()[0].strip("«»\"") not in text:
            continue
        sizes = [r.font.size.pt for p in sh.text_frame.paragraphs for r in p.runs if r.font.size is not None]
        size = max(sizes) if sizes else None
        if not size:
            continue
        family = next((r.font.name for p in sh.text_frame.paragraphs for r in p.runs if r.font.name), None)
        inner = (int(sh.width) - int(sh.text_frame.margin_left or 91440) - int(sh.text_frame.margin_right or 91440)) / EMU_PER_PT
        widest = max((text_width_pt(w, family, size) for w in text.split() if w), default=0.0)
        if widest > inner * 1.02:
            return f"breaks a word of its heading ({widest:.0f} pt in a {inner:.0f} pt box)"
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            ox = max(0, min(a.left + a.width, b.left + b.width) - max(a.left, b.left))
            oy = max(0, min(a.top + a.height, b.top + b.height) - max(a.top, b.top))
            small = min(a.width * a.height, b.width * b.height)
            if small > 0 and ox * oy > 0.2 * small:
                return "lays two of its texts over each other"
    return None


def _render_deck(outline: DeckOutline, plan: LayoutPlan, manifest: TemplateManifest, ws: TemplateWorkspace, out_pptx: Path | str, progress: Optional[Callable[[str, float], None]], skip: Optional[set] = None) -> RenderResult:
    t0 = time.time()
    builder = DeckBuilder(ws.source)
    patterns = {p.id: p for p in manifest.patterns}
    result = RenderResult(pptx_path=Path(out_pptx))
    n = len(outline.slides)
    used: dict[str, int] = {}  # template samples the deck's content slides stand on
    for i, oslide in enumerate(outline.slides, 1):
        ps = plan.for_outline(oslide.id) or LayoutSlide(outline_id=oslide.id, mode="synth", composition="bullets", reasons=["no plan entry"])
        # render-time guards (fallbacks.py): a chart without data, empty columns, a kind with no composition, template
        # stubs. What the deck shows is written back, so the audit and outline.json / layout_plan.json describe it
        safe, safe_ps, notes = prepare_slide(oslide, ps, outline)
        if safe is not oslide:
            outline.slides[i - 1] = oslide = safe
        if safe_ps is not ps:
            plan.slides = [safe_ps if s is ps else s for s in plan.slides]
            ps = safe_ps
        rendered = RenderedSlide(outline_id=oslide.id, index=i, mode=ps.mode, pattern_id=ps.pattern_id, composition=ps.composition)
        rendered.warnings.extend(notes)
        before = _snapshot(builder)
        try:
            kind_v = getattr(getattr(oslide, "kind", None), "value", str(getattr(oslide, "kind", "")))
            if ps.mode == "clone" and ps.pattern_id in patterns and kind_v not in _BOOKEND_VALUES:
                slide, warns = _render_content_clone(builder, ps, oslide, patterns, manifest, ws, outline, used, before, failed=result.failed_samples, skip=skip)
                rendered.pattern_id = ps.pattern_id
                used[ps.pattern_id] = used.get(ps.pattern_id, 0) + 1
            elif ps.mode == "clone" and ps.pattern_id in patterns:
                slide, warns = render_clone(builder, ps, oslide, patterns[ps.pattern_id], manifest, ws, outline)
                why = _bookend_trouble(slide, oslide)
                if why and KEPT_PHOTO in warns:
                    # the sample's photo kept beside the title left the title no room: the same cover without it
                    # before a composed one
                    _rollback(builder, before)
                    slide, warns = render_clone(builder, ps, oslide, patterns[ps.pattern_id], manifest, ws, outline, keep_photos=False)
                    why = _bookend_trouble(slide, oslide)
                if why:
                    # a cover set in a sample made for a short word (a title box a quarter of the slide wide, a word
                    # behind a product shot) breaks the deck's words or runs its lines together: composed instead
                    raise _CoverRedo(why)
            else:
                _, warns = render_synth(builder, ps, oslide, manifest, ws, outline)
            rendered.warnings.extend(warns)
        except Exception as e:  # noqa: BLE001
            if isinstance(e, _CoverRedo):
                log.info("slide %d (%s): the cloned cover %s — composed instead", i, oslide.id, e)
            elif isinstance(e, _CloneRedo):
                log.info("slide %d (%s): no template sample holds it (%s) — composed", i, oslide.id, e)
            else:
                log.exception("slide %d (%s) failed in mode %s", i, oslide.id, ps.mode)
            rendered.warnings.append(f"{ps.mode} failed: {str(e)[:160]}; fell back to synth")
            # a half-filled clone must not stay in the deck next to its synth replacement
            _rollback(builder, before)
            try:
                fallback = LayoutSlide(outline_id=oslide.id, mode="synth", composition=fallback_composition(oslide, ps))
                _, warns = render_synth(builder, fallback, oslide, manifest, ws, outline)
                rendered.mode, rendered.composition = "synth", fallback.composition
                rendered.pattern_id = None
                if isinstance(e, _CloneRedo):
                    # the plan says what the deck shows: the slide composed, with the samples that did not hold it
                    fallback.fit, fallback.score, fallback.alternatives = ps.fit, ps.score, ps.alternatives
                    fallback.reasons = [f"композиция {fallback.composition}: образцы шаблона не вместили содержимое ({str(e)[:160]})"]
                    plan.slides = [fallback if s is ps else s for s in plan.slides]
                rendered.warnings.extend(warns)
            except Exception as e2:  # noqa: BLE001
                log.exception("synth fallback failed for slide %d", i)
                rendered.warnings.append(f"synth fallback failed: {str(e2)[:160]}")
                _rollback(builder, before)
        if len(builder.created) > before[0]:
            _mark_notes(builder, oslide)  # only a slide made for this outline entry carries its marker
            try:
                from verstka.rendering.synth import unreadable_text_pass

                n_fix = unreadable_text_pass(builder.created[-1], manifest)
                if n_fix:
                    rendered.warnings.append(f"{n_fix} text run(s) all but invisible on their ground recoloured")
            except Exception:  # noqa: BLE001 - a guard, never a failure
                log.debug("unreadable text pass failed on slide %d", i, exc_info=True)
        result.slides.append(rendered)
        if progress:
            progress(f"rendered slide {i}/{n}", i / max(n, 1))
    builder.delete_original_slides()
    _give_geometry(builder)
    builder.save(out_pptx)
    result.seconds = round(time.time() - t0, 2)
    log.info("rendered %d slides to %s in %.1fs", len(result.slides), out_pptx, result.seconds)
    return result
