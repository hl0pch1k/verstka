"""match_outline: choose a pattern (clone) or a composition (synth) for every outline slide."""

from __future__ import annotations

from collections import deque
from typing import Optional

from verstka.matching.compat import composition_for, kind_compat
from verstka.matching.scorer import score_pattern
from verstka.planning.strategies import Strategy
from verstka.schemas.common import Family
from verstka.schemas.layout import LayoutPlan, LayoutSlide
from verstka.schemas.outline import DeckOutline
from verstka.schemas.template import TemplateManifest


def match_outline(outline: DeckOutline, manifest: TemplateManifest, strategy: Strategy, min_quality: float = 0.2) -> LayoutPlan:
    plan = LayoutPlan(strategy=strategy.name, template_id=manifest.template_id)
    recent: deque[str] = deque(maxlen=3)
    prev_family: Optional[Family] = None
    candidates = [p for p in manifest.patterns if p.quality >= min_quality]
    for slide in outline.slides:
        scored = []
        for p in candidates:
            if kind_compat(slide.kind, p.kind) <= 0:
                continue
            res = score_pattern(slide, p, manifest, strategy, prev_family, list(recent))
            scored.append((res, p))
        scored.sort(key=lambda t: -t[0].score)
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
