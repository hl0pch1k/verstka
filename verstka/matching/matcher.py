"""match_outline: choose a pattern (clone) or a composition (synth) for every outline slide."""

from __future__ import annotations

from collections import deque
from typing import Optional

from verstka.matching.compat import composition_for, kind_compat
from verstka.matching.scorer import _bookend_title_fit, cover_goal, display_lines, score_pattern, split_display_title
from verstka.planning.strategies import Strategy
from verstka.schemas.common import Family, PatternKind, SlotRole
from verstka.schemas.layout import LayoutPlan, LayoutSlide
from verstka.schemas.outline import DeckOutline
from verstka.schemas.template import Pattern, TemplateManifest


VISUAL_COVER_MARGIN = 0.15  # how far below the best cover the visual variant's other cover may score


def _cover_room_ok(slide, pattern: Pattern, manifest: TemplateManifest) -> bool:
    """The other cover holds the whole stack — the heading at its fitted size, the subtitle and a goal line under it —
    in the room its sample's own texts take (from the top of its heading to the foot of its lowest text box), with a
    seventh to spare. A centred cover whose art stands right under a one-line heading (VK Tech's glass cube) takes a
    short title; a two-line one would run over the art."""
    got = _bookend_title_fit(slide, pattern, manifest)
    if got is None:
        return False
    size, lines, _, t = got
    texts = [s for s in pattern.slots if s.role in (SlotRole.title, SlotRole.subtitle, SlotRole.body, SlotRole.caption)]
    H = manifest.slide_size.h / 12700
    room = (max(s.bbox.y + s.bbox.h for s in texts) - t.bbox.y) * H
    typo = manifest.tokens.typography
    sub_slot = next((s for s in pattern.slots if s.role == SlotRole.subtitle), None)
    sub_size = (sub_slot.style.size_pt if sub_slot is not None and sub_slot.style.size_pt else None) or typo.size_for("h2", 16.0)
    width = max(t.bbox.w * manifest.slide_size.w / 12700 - 14.4, 40.0)
    need = lines * size * 1.2
    sub = slide.subtitle or split_display_title(slide.headline)[1]
    if sub:
        need += 0.25 * size + len(display_lines(sub, typo.primary_family, sub_size, False, width)) * sub_size * 1.2
    goal = cover_goal(slide)
    if goal:
        g = 0.8 * sub_size
        need += 0.6 * g + len(display_lines(goal, typo.primary_family, g, False, width)) * g * 1.2
    return need <= room * 1.15


def headline_key(slide) -> str:
    """The slide across variants: its kind-free heading, lower case, spaces collapsed."""
    return " ".join((slide.headline or "").lower().split())[:120]


# reuse of one sample in a deck: the second appearance costs this much, the third more — a template of fifty slides
# shown through five of them loses what makes it the template
REUSE_PENALTY = (0.0, 0.22, 0.45, 0.7)
NEIGHBOUR_PENALTY = 0.4  # the same sample on two neighbouring slides reads as a copy
OTHER_VARIANT_PENALTY = 0.3  # the same sample for the same slide in a variant already built: variants should differ


def _assign_content(entries: list[dict], strategy: Strategy, taken: Optional[dict[str, set[str]]]) -> dict[int, tuple]:
    """Template samples for the content slides of a deck: the most constrained slide chooses first; a sample already
    used costs more each time, the same sample never stands on two neighbouring slides, a sample another variant used
    for this very slide costs a little. Returns slide index → (adjusted score, result, pattern)."""
    from collections import Counter

    uses: Counter = Counter()
    chosen: dict[int, tuple] = {}
    order = sorted(entries, key=lambda e: (len(e["cands"]), e["index"]))
    for e in order:
        i = e["index"]
        best = None
        for res, p in e["cands"]:
            adj = res.score - REUSE_PENALTY[min(uses[p.id], len(REUSE_PENALTY) - 1)]
            if any(j in chosen and chosen[j][2].id == p.id for j in (i - 1, i + 1)):
                adj -= NEIGHBOUR_PENALTY
            if taken and p.id in taken.get(e["key"], set()):
                adj -= OTHER_VARIANT_PENALTY
            if best is None or adj > best[0] + 1e-9:
                best = (adj, res, p)
        if best is not None and best[0] >= strategy.clone_fit - 0.12:
            chosen[i] = best
            uses[best[2].id] += 1
    return chosen


def match_outline(outline: DeckOutline, manifest: TemplateManifest, strategy: Strategy, min_quality: float = 0.2, ws=None, taken: Optional[dict[str, set[str]]] = None, exclude: Optional[set[tuple[str, str]]] = None) -> LayoutPlan:
    """`ws`: the template's workspace — its sample pictures are read to tell art (kept) from a sample's own story
    (`analysis.pictures`). `taken`: headline key → samples the variants built before used for that slide; filled in
    with this variant's choices. `exclude`: (outline id, sample id) pairs a render of the deck found reading badly
    (`renderer.RenderResult.failed_samples`): the deck's samples are chosen without them."""
    exclude = exclude or set()
    plan = LayoutPlan(strategy=strategy.name, template_id=manifest.template_id)
    recent: deque[str] = deque(maxlen=3)
    prev_family: Optional[Family] = None
    cover: Optional[Pattern] = None  # the sample of the cover: the closing slide answers it
    divider: Optional[Pattern] = None  # the sample of the first section divider: the others repeat it
    candidates = [p for p in manifest.patterns if p.quality >= min_quality]
    pictures: dict = {}
    if ws is not None:
        try:
            from verstka.analysis.pictures import sample_pictures

            pictures = sample_pictures(ws, manifest)
        except Exception:  # noqa: BLE001 - without them every picture counts as the sample's own
            pictures = {}
    clone_content = strategy.clone_fit <= 1.2
    deferred: list[dict] = []  # content slides waiting for the deck-level choice of samples
    for slide in outline.slides:
        scored = []
        for p in candidates:
            if kind_compat(slide.kind, p.kind) <= 0 or (slide.id, p.id) in exclude:
                continue
            res = score_pattern(slide, p, manifest, strategy, prev_family, list(recent), cover=cover, divider=divider, pictures=pictures.get(p.id) if pictures else None)
            scored.append((res, p))
        scored.sort(key=lambda t: -t[0].score)
        if slide.kind == PatternKind.section and divider is not None:
            # every divider of a deck is the same slide: the first one's sample stays while it is usable at all
            same = next((i for i, (r, q) in enumerate(scored) if q.id == divider.id and r.score >= strategy.synth_threshold), None)
            if same:
                scored.insert(0, scored.pop(same))
        if slide.kind == PatternKind.title and len(scored) > 1 and not _cover_room_ok(slide, scored[0][1], manifest):
            # a cover whose stack (heading, subtitle, goal) does not fit the room its sample's own texts take gives way
            # to another cover of the template within the margin that holds it: «История VK» with a 50-character
            # subtitle takes VK Tech's left-aligned cover, not the centred one whose cube stands right under a one-line
            # subtitle (G1-20). Never a cover whose layout draws a mock-up or a photo frame left empty
            top = scored[0]
            for i, (r, q) in enumerate(scored[1:], 1):
                if top[0].score - r.score > VISUAL_COVER_MARGIN:
                    break
                stays_empty = bool(q.mockup_boxes) and q.mockup_on_layout and not slide.content.image_hint
                if q.kind == PatternKind.title and r.score >= strategy.synth_threshold and not any(s.role == SlotRole.image for s in q.slots) and not stays_empty and _cover_room_ok(slide, q, manifest):
                    r.reasons.append(f"обложка: весь блок текста помещается в образец {q.id} ({r.score:.2f}), в {top[1].id} ({top[0].score:.2f}) — нет")
                    scored.insert(0, scored.pop(i))
                    break
        if slide.kind == PatternKind.title and strategy.name == "visual" and len(scored) > 1:
            # the visual variant opens on the template's other cover when it is nearly as good (another layout, no speaker
            # photo to leave empty, the title fits): flipping between variants, the first slide differs too. «Nearly»
            # is a margin of 0.15: the cover bonus of a sample whose art stands beside the heading (+0.1 over a centred
            # one) must not decide alone that the variants open alike
            top = scored[0]
            for i, (r, q) in enumerate(scored[1:], 1):
                if top[0].score - r.score > VISUAL_COVER_MARGIN:
                    break
                # a device mock-up or an empty photo frame the layout draws stays empty on the slide: never the
                # «other cover» (the −0.3 of the scorer is within the margin)
                stays_empty = bool(q.mockup_boxes) and q.mockup_on_layout and not slide.content.image_hint
                if q.layout_part != top[1].layout_part and q.kind == PatternKind.title and not any(s.role == SlotRole.image for s in q.slots) and not stays_empty and r.fit.get("text_ratio", 9.0) <= 1.0 and _cover_room_ok(slide, q, manifest):
                    r.reasons.append(f"вариант visual: другой титульный образец ({r.score:.2f} против {top[0].score:.2f}), чтобы варианты различались с первого слайда")
                    scored.insert(0, scored.pop(i))
                    break
        covers = slide.kind in (PatternKind.title, PatternKind.section, PatternKind.thanks)
        if clone_content and not covers:
            # content slides choose their samples together, once the deck is known (`_assign_content`)
            cands = [(r, q) for r, q in scored if r.score >= strategy.clone_fit - 0.12 and q.kind not in (PatternKind.title, PatternKind.section, PatternKind.thanks)]
            deferred.append({"index": len(plan.slides), "key": headline_key(slide), "slide": slide, "scored": scored, "cands": cands})
            plan.slides.append(LayoutSlide(outline_id=slide.id, mode="synth", composition=composition_for(slide)))
            continue
        if strategy.compose_content and not covers and not (scored and scored[0][0].score >= strategy.clone_fit):
            comp = composition_for(slide)
            plan.slides.append(
                LayoutSlide(
                    outline_id=slide.id,
                    mode="synth",
                    composition=comp,
                    fit=scored[0][0].fit if scored else {},
                    score=scored[0][0].score if scored else 0.0,
                    reasons=[f"композиция {comp}: сетка, шкала кеглей и карточки из дизайн-системы шаблона"]
                    + ([f"ближайший образец — слайд {scored[0][1].source_slide} шаблона ({scored[0][0].score:.2f})"] if scored else []),
                    alternatives=[(q.id, r.score) for r, q in scored[:3]],
                )
            )
            continue
        if scored and scored[0][0].score >= strategy.synth_threshold:
            res, p = scored[0]
            plan.slides.append(
                LayoutSlide(
                    outline_id=slide.id,
                    mode="clone",
                    pattern_id=p.id,
                    fit=res.fit,
                    score=res.score,
                    reasons=[f"слайд {p.source_slide} шаблона"] + res.reasons,
                    alternatives=[(q.id, r.score) for r, q in scored[1:4]],
                )
            )
            recent.append(p.id)
            prev_family = p.family if slide.kind.value not in ("title", "section", "thanks") else prev_family
            if slide.kind == PatternKind.title and cover is None:
                cover = p
            elif slide.kind == PatternKind.section and divider is None:
                divider = p
        else:
            comp = composition_for(slide)
            why = "нет подходящего паттерна в шаблоне" if not scored else f"лучший паттерн {scored[0][1].id} набрал {scored[0][0].score:.2f} < порога {strategy.synth_threshold}"
            plan.slides.append(
                LayoutSlide(
                    outline_id=slide.id,
                    mode="synth",
                    composition=comp,
                    fit=scored[0][0].fit if scored else {},
                    score=scored[0][0].score if scored else 0.0,
                    reasons=[why, f"композиция {comp} из компонентов шаблона"],
                    alternatives=[(q.id, r.score) for r, q in scored[:3]],
                )
            )
    if deferred:
        chosen = _assign_content(deferred, strategy, taken)
        in_deck = {got[2].id for got in chosen.values()}
        for e in deferred:
            i, slide, scored = e["index"], e["slide"], e["scored"]
            got = chosen.get(i)
            if got is not None:
                adj, res, p = got
                note = [] if abs(adj - res.score) < 1e-6 else [f"разнообразие колоды: {res.score:.2f} → {adj:.2f} (образец уже встречался рядом, в колоде или в другом варианте)"]
                # the fallbacks of a slide whose sample reads badly: samples no other slide of the deck stands on first
                others = [(q.id, r.score) for r, q in scored if q.id != p.id]
                alts = [a for a in others if a[0] not in in_deck] + [a for a in others if a[0] in in_deck]
                plan.slides[i] = LayoutSlide(
                    outline_id=slide.id,
                    mode="clone",
                    pattern_id=p.id,
                    fit=res.fit,
                    score=res.score,
                    reasons=[f"слайд {p.source_slide} шаблона"] + res.reasons + note,
                    alternatives=alts[:5],
                )
                if taken is not None:
                    taken.setdefault(e["key"], set()).add(p.id)
            else:
                comp = composition_for(slide)
                plan.slides[i] = LayoutSlide(
                    outline_id=slide.id,
                    mode="synth",
                    composition=comp,
                    fit=scored[0][0].fit if scored else {},
                    score=scored[0][0].score if scored else 0.0,
                    reasons=[f"композиция {comp}: сетка, шкала кеглей и карточки из дизайн-системы шаблона"]
                    + ([f"ближайший образец — слайд {scored[0][1].source_slide} шаблона ({scored[0][0].score:.2f}) не подходит по наполнению"] if scored else []),
                    alternatives=[(q.id, r.score) for r, q in scored[:3]],
                )
    return plan
