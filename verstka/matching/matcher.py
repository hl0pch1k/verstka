"""match_outline: choose a pattern (clone) or a composition (synth) for every outline slide."""

from __future__ import annotations

from collections import deque
from typing import Optional

from verstka.matching.compat import composition_for, kind_compat
from verstka.matching.scorer import score_pattern
from verstka.planning.strategies import Strategy
from verstka.schemas.common import Family, PatternKind, SlotRole
from verstka.schemas.layout import LayoutPlan, LayoutSlide
from verstka.schemas.outline import DeckOutline
from verstka.schemas.template import Pattern, TemplateManifest


def match_outline(outline: DeckOutline, manifest: TemplateManifest, strategy: Strategy, min_quality: float = 0.2) -> LayoutPlan:
    plan = LayoutPlan(strategy=strategy.name, template_id=manifest.template_id)
    recent: deque[str] = deque(maxlen=3)
    prev_family: Optional[Family] = None
    cover: Optional[Pattern] = None  # the sample of the cover: the closing slide answers it
    divider: Optional[Pattern] = None  # the sample of the first section divider: the others repeat it
    candidates = [p for p in manifest.patterns if p.quality >= min_quality]
    for slide in outline.slides:
        scored = []
        for p in candidates:
            if kind_compat(slide.kind, p.kind) <= 0:
                continue
            res = score_pattern(slide, p, manifest, strategy, prev_family, list(recent), cover=cover, divider=divider)
            scored.append((res, p))
        scored.sort(key=lambda t: -t[0].score)
        if slide.kind == PatternKind.section and divider is not None:
            # every divider of a deck is the same slide: the first one's sample stays while it is usable at all
            same = next((i for i, (r, q) in enumerate(scored) if q.id == divider.id and r.score >= strategy.synth_threshold), None)
            if same:
                scored.insert(0, scored.pop(same))
        if slide.kind == PatternKind.title and strategy.name == "visual" and len(scored) > 1:
            # the visual variant opens on the template's other cover when it is nearly as good (another layout, no speaker
            # photo to leave empty, the title fits): flipping between variants, the first slide differs too
            top = scored[0]
            for i, (r, q) in enumerate(scored[1:], 1):
                if top[0].score - r.score > 0.06:
                    break
                if q.layout_part != top[1].layout_part and q.kind == PatternKind.title and not any(s.role == SlotRole.image for s in q.slots) and r.fit.get("text_ratio", 9.0) <= 1.0:
                    r.reasons.append(f"вариант visual: другой титульный образец ({r.score:.2f} против {top[0].score:.2f}), чтобы варианты различались с первого слайда")
                    scored.insert(0, scored.pop(i))
                    break
        covers = slide.kind in (PatternKind.title, PatternKind.section, PatternKind.thanks)
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
    return plan
