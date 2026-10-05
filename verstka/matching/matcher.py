"""match_outline: choose a pattern (clone) or a composition (synth) for every outline slide."""

from __future__ import annotations

from collections import deque
from typing import Optional

from verstka.matching.compat import composition_for, kind_compat
from verstka.matching.scorer import chart_picture_room, _bookend_title_fit, cover_goal, display_lines, score_pattern, split_display_title
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


def _cover_sample(pattern: Pattern, manifest: TemplateManifest) -> bool:
    """A sample that is a cover in its own right: its heading set at a display size (7 % of the slide height, or a
    good step over the content heading), or the template's first title layout — never a content layout classed a
    divider (LCT p19: a 20 pt heading pill over a white panel opened the compact deck with its title at 9.7 pt)."""
    from verstka.matching.scorer import _cover_like

    t = next((x for x in pattern.slots if x.role == SlotRole.title), None)
    size = (t.style.size_pt if t is not None and t.style.size_pt else 0.0) or 0.0
    h1 = manifest.tokens.typography.size_for("h1", 32.0)
    return _cover_like(pattern, manifest, size) or size >= 1.15 * h1


COVER_ORDER = {"structured": 0, "visual": 1, "compact": 2}
COVER_MARGIN = 0.22  # how far below the best cover another variant's own cover may score
LIGHT_COVER_MARGIN = 0.45  # the compact variant's light cover (a divider of the template's light ground, say) may stand this far below


def variant_cover(slide, scored: list, manifest: TemplateManifest, strategy: Strategy) -> Optional[int]:
    """The index in `scored` of the cover this variant opens on: of the template's covers that hold the slide's title
    (a title sample, or a divider's when its title fits), one of each layout and ground, within `COVER_MARGIN` of the
    best — the structured variant the best, the visual one the next, the compact one a light cover (the next after
    the visual's when the template has no light one). None when there is no choice."""
    if not scored:
        return None
    top = scored[0][0].score
    usable: list[int] = []
    seen: set = set()
    for i, (r, q) in enumerate(scored):
        if top - r.score > COVER_MARGIN:
            break
        if q.kind not in (PatternKind.title, PatternKind.section) or r.score < strategy.synth_threshold:
            continue
        stays_empty = bool(q.mockup_boxes) and q.mockup_on_layout and not slide.content.image_hint
        if stays_empty or (i > 0 and any(s.role == SlotRole.image for s in q.slots)) or (i > 0 and r.fit.get("text_ratio", 9.0) > 1.0):
            continue
        if i > 0 and not _cover_room_ok(slide, q, manifest):
            continue
        key = (q.layout_part, q.family)
        if key in seen:
            continue
        seen.add(key)
        usable.append(i)
    if not usable:
        return None
    if strategy.name == "compact" and scored[usable[0]][1].family != Family.light:
        # the compact variant reads like a document: a light cover (a light title sample, else a light divider whose
        # title holds the deck's name) — further below the best cover than the others may stand
        for i, (r, q) in enumerate(scored):
            if top - r.score > LIGHT_COVER_MARGIN or i in usable:
                continue
            if q.family == Family.light and q.kind in (PatternKind.title, PatternKind.section) and r.score >= strategy.synth_threshold \
                    and not any(s.role == SlotRole.image for s in q.slots) and r.fit.get("text_ratio", 9.0) <= 1.15 and _cover_room_ok(slide, q, manifest) \
                    and not (bool(q.mockup_boxes) and q.mockup_on_layout and not slide.content.image_hint) \
                    and (top - r.score <= COVER_MARGIN or _cover_sample(q, manifest)):
                usable.append(i)
                break
        light = [i for i in usable if scored[i][1].family == Family.light]
        if light:
            return light[0]
    if len(usable) < 2:
        return None
    k = COVER_ORDER.get(strategy.name, 0)
    return usable[min(k, len(usable) - 1)]


def headline_key(slide) -> str:
    """The slide across variants: its kind-free heading, lower case, spaces collapsed."""
    return " ".join((slide.headline or "").lower().split())[:120]


# reuse of one sample in a deck: the second appearance costs this much, the third more — a template of fifty slides
# shown through five of them loses what makes it the template
REUSE_PENALTY = (0.0, 0.22, 0.45, 0.7)
NEIGHBOUR_PENALTY = 0.4  # the same sample on two neighbouring slides reads as a copy
OTHER_VARIANT_PENALTY = 0.3  # the same sample for the same slide in a variant already built: variants should differ
GROUND_PENALTY = 0.05  # a neighbour on the other ground (dark after light): close choices keep the deck's ground


def layout_signature(p: Pattern) -> tuple:
    """What a sample looks like, whatever its id: its layout, its kind, its text boxes by role (rounded to 2 % of the
    slide) and its repeat groups. Twins of a template (VK Education p26/p27: one row of coloured shapes with their
    captions, drawn twice) share it — shown on two neighbouring slides they read as one slide twice."""
    boxes = tuple(sorted((s.role.value, round(s.bbox.x / 0.02), round(s.bbox.y / 0.02), round(s.bbox.w / 0.02), round(s.bbox.h / 0.02)) for s in p.slots if s.role in _TEXT_ROLES))
    groups = tuple(sorted((g.axis, len(g.member_shape_ids)) for g in p.repeat_groups))
    return (p.layout_part, p.kind.value, boxes, groups)


_TEXT_ROLES = {SlotRole.title, SlotRole.subtitle, SlotRole.body, SlotRole.bullet_list, SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.caption}


def _assign_content(entries: list[dict], strategy: Strategy, taken: Optional[dict[str, set[str]]], sig: Optional[dict] = None) -> dict[int, tuple]:
    """Template samples for the content slides of a deck: the most constrained slide chooses first; a sample already
    used costs more each time, the same sample never stands on two neighbouring slides, a sample another variant used
    for this very slide costs a little — a sample and its twin (`layout_signature`) count as one. Returns slide index
    → (adjusted score, result, pattern)."""
    from collections import Counter

    sig = sig or {}
    same = lambda pid: sig.get(pid, pid)  # noqa: E731
    uses: Counter = Counter()
    chosen: dict[int, tuple] = {}
    order = sorted(entries, key=lambda e: (len(e["cands"]), e["index"]))
    for e in order:
        i = e["index"]
        best = None
        others = {same(x) for x in (taken or {}).get(e["key"], set())}
        for res, p in e["cands"]:
            k = same(p.id)
            adj = res.score - REUSE_PENALTY[min(uses[k], len(REUSE_PENALTY) - 1)]
            if any(j in chosen and same(chosen[j][2].id) == k for j in (i - 1, i + 1)):
                adj -= NEIGHBOUR_PENALTY
            adj -= GROUND_PENALTY * sum(1 for j in (i - 1, i + 1) if j in chosen and chosen[j][2].family != p.family)
            if k in others:
                adj -= OTHER_VARIANT_PENALTY
            if best is None or adj > best[0] + 1e-9:
                best = (adj, res, p)
        if best is not None and best[0] >= strategy.clone_fit - 0.12:
            chosen[i] = best
            uses[same(best[2].id)] += 1
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
            if (slide.id, p.id) in exclude:
                continue
            if kind_compat(slide.kind, p.kind) <= 0 and not chart_picture_room(slide, p, pictures.get(p.id) if pictures else None):
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
        if slide.kind == PatternKind.title and len(scored) > 1:
            # every variant opens on a cover of its own when the template has several that hold the title (another
            # layout or another ground, no speaker photo or mock-up to leave empty): flipping between variants, the
            # first slide differs too — the compact variant on a light one when there is one, the visual one on the
            # template's second cover
            pick = variant_cover(slide, scored, manifest, strategy)
            if pick is not None and pick != 0:
                r, q = scored[pick]
                r.reasons.append(f"вариант {strategy.name}: свой титульный образец ({r.score:.2f} против {scored[0][0].score:.2f}), чтобы варианты различались с первого слайда")
                scored.insert(0, scored.pop(pick))
        if slide.kind == PatternKind.thanks and cover is not None and len(scored) > 1 and scored[0][1].family != cover.family:
            # the closing slide answers the cover's ground: a deck opened on a light cover closes on a light slide
            top = scored[0]
            for i, (r, q) in enumerate(scored[1:], 1):
                if top[0].score - r.score > LIGHT_COVER_MARGIN:
                    break
                if q.family == cover.family and q.kind in (PatternKind.thanks, PatternKind.section, PatternKind.title) and r.score >= strategy.synth_threshold \
                        and not any(x.role == SlotRole.image for x in q.slots) and r.fit.get("text_ratio", 9.0) <= 1.15 and _cover_room_ok(slide, q, manifest):
                    r.reasons.append(f"закрывает колоду на том же фоне, что и обложка ({cover.family.value})")
                    scored.insert(0, scored.pop(i))
                    break
        covers = slide.kind in (PatternKind.title, PatternKind.section, PatternKind.thanks)
        if clone_content and not covers:
            # content slides choose their samples together, once the deck is known (`_assign_content`)
            cands = [(r, q) for r, q in scored if r.score >= strategy.clone_fit - 0.12 and q.kind not in (PatternKind.title, PatternKind.section, PatternKind.thanks)]
            if (slide.content.formula or "").strip():
                # an equation is the composer's (the render's gate turns every sample down for it): a sample planned
                # for it only costs the slides that could stand on it
                cands = []
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
        chosen = _assign_content(deferred, strategy, taken, {p.id: layout_signature(p) for p in manifest.patterns})
        in_deck = {got[2].id for got in chosen.values()}
        for e in deferred:
            i, slide, scored = e["index"], e["slide"], e["scored"]
            got = chosen.get(i)
            if got is not None:
                adj, res, p = got
                note = [] if abs(adj - res.score) < 1e-6 else [f"разнообразие колоды: {res.score:.2f} → {adj:.2f} (образец уже встречался рядом, в колоде или в другом варианте)"]
                # the fallbacks of a slide whose sample reads badly: by score, a sample another slide of the deck stands
                # on counted as a reuse — and only those the render would try (its floor: the first one's score less
                # 0.3, within 0.45…0.6), so five low ones never shut out a good one used elsewhere in the deck
                floor = max(0.45, min(res.score - 0.3, 0.6))
                others = [(q.id, r.score) for r, q in scored if q.id != p.id and r.score >= floor and q.kind not in (PatternKind.title, PatternKind.section, PatternKind.thanks)]
                alts = sorted(others, key=lambda a: -(a[1] - (REUSE_PENALTY[1] if a[0] in in_deck else 0.0)))
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
