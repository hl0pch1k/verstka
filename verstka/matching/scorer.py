"""Explainable scoring of a template pattern for an outline slide."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from verstka.matching.compat import kind_compat, needed_chars, needed_items
from verstka.planning.strategies import Strategy
from verstka.schemas.common import Family, PatternKind, SlotRole
from verstka.schemas.outline import OutlineSlide
from verstka.schemas.template import Pattern, TemplateManifest

_GROUP_ROLES = {SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.icon}
_STANDALONE_KINDS = {PatternKind.title, PatternKind.section, PatternKind.thanks, PatternKind.quote}


@dataclass
class ScoreResult:
    score: float
    reasons: list[str] = field(default_factory=list)
    fit: dict = field(default_factory=dict)


def _slot_capacity(pattern: Pattern, role: SlotRole) -> int:
    """Capacity for one instance of the role (first cell for grouped roles, sum for standalone roles)."""
    slots = [s for s in pattern.slots if s.role == role]
    if not slots:
        return 0
    if role in _GROUP_ROLES:
        grouped = [s for s in slots if s.group_id]
        return max((s.capacity.max_chars for s in (grouped or slots)), default=0)
    return sum(s.capacity.max_chars for s in slots)


def score_pattern(
    slide: OutlineSlide,
    pattern: Pattern,
    manifest: TemplateManifest,
    strategy: Strategy,
    prev_family: Optional[Family] = None,
    recent_ids: Optional[list[str]] = None,
) -> ScoreResult:
    recent_ids = recent_ids or []
    reasons: list[str] = []
    fit: dict = {}
    kind = kind_compat(slide.kind, pattern.kind)
    if kind <= 0:
        return ScoreResult(0.0, [f"тип {pattern.kind.value} несовместим с {slide.kind.value}"], fit)
    reasons.append(f"тип {pattern.kind.value} для {slide.kind.value}: {kind:.1f}")

    # capacity in items
    n = needed_items(slide)
    cap = 1.0
    group = max(pattern.repeat_groups, key=lambda g: len(g.member_shape_ids), default=None)
    if n >= 2:
        if group is not None:
            fit["items"] = f"{n}/{group.max_n}"
            if group.min_n <= n <= group.max_n:
                cap = 1.0
                reasons.append(f"ёмкость группы {n} из {group.max_n} ячеек")
            elif n > group.max_n:
                cap = max(0.2, 1.0 - 0.25 * (n - group.max_n))
                reasons.append(f"не хватает ячеек: нужно {n}, максимум {group.max_n}")
        else:
            role_slots = sum(1 for s in pattern.slots if s.role in (SlotRole.card_title, SlotRole.number, SlotRole.bullet_list, SlotRole.body))
            if slide.kind in (PatternKind.bullets, PatternKind.agenda) and any(s.role == SlotRole.bullet_list for s in pattern.slots):
                cap = 1.0
                reasons.append("список помещается в один слот")
            elif role_slots >= n:
                cap = 0.8
                reasons.append(f"{role_slots} отдельных слотов под {n} элементов")
            else:
                cap = 0.25
                reasons.append(f"нет повторяющейся группы под {n} элементов")
            fit["items"] = f"{n}/{role_slots}"

    # text fit
    worst = 0.0
    for role_name, need in needed_chars(slide).items():
        role = SlotRole(role_name)
        capacity = _slot_capacity(pattern, role)
        if capacity == 0:
            # bullets may go into a body slot and vice versa
            alt = {SlotRole.bullet_list: SlotRole.body, SlotRole.body: SlotRole.bullet_list, SlotRole.subtitle: SlotRole.body, SlotRole.card_body: SlotRole.body}.get(role)
            capacity = _slot_capacity(pattern, alt) if alt else 0
        if capacity == 0:
            ratio = 0.0 if need == 0 else (0.5 if role in (SlotRole.subtitle, SlotRole.number_label) else 2.0)
        else:
            ratio = need / capacity
        worst = max(worst, ratio)
        if ratio > 1.0:
            fit[f"overflow_{role_name}"] = round(ratio, 2)
    fit["text_ratio"] = round(worst, 2)
    if worst <= 1.0:
        text = 1.0
        reasons.append("текст помещается")
    elif worst <= 1.3:
        text = 0.7
        reasons.append(f"текст чуть длиннее ёмкости (×{worst:.2f}), нужен меньший кегль")
    elif worst <= 1.8:
        text = 0.4
        reasons.append(f"текст заметно длиннее ёмкости (×{worst:.2f}), потребуется сокращение")
    else:
        text = 0.15
        reasons.append(f"текст не помещается (×{worst:.2f})")

    # family continuity
    fam = 1.0
    if slide.kind not in _STANDALONE_KINDS and prev_family is not None and pattern.family != prev_family:
        fam = 0.5
        reasons.append(f"семья {pattern.family.value} отличается от предыдущего слайда")

    diversity = -0.15 if pattern.id in recent_ids else 0.0
    if diversity:
        reasons.append("паттерн уже использован недавно")
    weight = strategy.weight(pattern.kind.value)
    if weight != 1.0:
        reasons.append(f"вес стратегии {strategy.name}: ×{weight:.2f}")
    base = 0.4 * kind + 0.25 * cap + 0.15 * text + 0.05 * fam + 0.1 * pattern.quality + diversity
    score = max(0.0, min(1.2, base * weight))
    return ScoreResult(round(score, 3), reasons, fit)
