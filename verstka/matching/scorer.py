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
_CONTENT_ROLES = (SlotRole.body, SlotRole.bullet_list, SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.caption)
_NUMBER_KINDS = {PatternKind.stat_row, PatternKind.big_number}


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


def _number_holders(pattern: Pattern, group) -> int:
    """How many figures the clone renderer can place: the cells of the text group (grown up to max_n), otherwise the standalone number slots.

    Numbers are never merged, so every figure beyond this count is lost.
    """
    if group is not None:
        return max(len(group.member_shape_ids), group.max_n)
    return sum(1 for s in pattern.slots if s.role == SlotRole.number and not s.group_id)


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

    # chart / table / quote need room
    slide_kind = slide.kind
    if slide_kind in (PatternKind.chart, PatternKind.table):
        big = [s for s in pattern.slots if s.role in (SlotRole.image, SlotRole.body, SlotRole.bullet_list) and s.bbox.area >= 0.12]
        if pattern.kind not in (PatternKind.chart, PatternKind.table) and not big:
            kind *= 0.3
            reasons.append("нет крупной области под диаграмму или таблицу")
    if slide_kind == PatternKind.quote and slide.content.quote:
        cap_q = max((s.capacity.max_chars for s in pattern.slots if s.role in (SlotRole.body, SlotRole.bullet_list, SlotRole.card_body, SlotRole.subtitle)), default=0)
        if cap_q < len(slide.content.quote) * 0.8:
            kind *= 0.5
            reasons.append("слоты слишком малы для цитаты")
        if any(len(g.member_shape_ids) >= 3 for g in pattern.repeat_groups):
            kind *= 0.4
            reasons.append("список ячеек не подходит для цитаты")

    # capacity in items
    n = needed_items(slide)
    cap = 1.0
    text_group_roles = (SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.bullet_list, SlotRole.body)
    groups = [g for g in pattern.repeat_groups if any(s.group_id == g.id and s.role in text_group_roles for s in pattern.slots)]
    group = max(groups, key=lambda g: len(g.member_shape_ids), default=None)
    if n >= 2:
        if group is not None:
            n_cells = len(group.member_shape_ids)
            fit["items"] = f"{n}/{group.max_n}"
            if group.min_n <= n <= group.max_n:
                cap = 1.0
                reasons.append(f"ёмкость группы {n} из {group.max_n} ячеек")
                if n_cells > 2 * n + 2:
                    cap = 0.75
                    reasons.append(f"группа из {n_cells} ячеек заметно больше нужных {n}")
            elif n > group.max_n:
                cap = 0.15 if n > group.max_n + 1 else 0.4
                reasons.append(f"не хватает ячеек: нужно {n}, максимум {group.max_n}")
            if group.cell_bbox.area < 0.02 and slide_kind in (PatternKind.cards, PatternKind.process, PatternKind.comparison, PatternKind.team, PatternKind.two_column):
                cap = min(cap, 0.2)
                reasons.append("ячейки слишком малы для карточек")
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
    # hard gates: a pattern without room for the slide's content would render a headline over stale sample shapes
    content = slide.content
    needed_roles = needed_chars(slide)
    content_need = sum(v for k, v in needed_roles.items() if k not in ("title", "subtitle"))
    content_cap = sum(s.capacity.max_chars for s in pattern.slots if s.role in _CONTENT_ROLES)
    has_data_object = content.chart is not None or content.table is not None
    if content_need > 0 and content_cap == 0 and not has_data_object:
        return ScoreResult(0.0, reasons + ["в паттерне нет ни одного слота под содержимое"], fit)
    if content_need > 0 and content_cap < 0.35 * content_need and not has_data_object:
        kind *= 0.3
        reasons.append(f"ёмкость слотов ({content_cap} симв.) намного меньше объёма содержимого ({content_need} симв.)")
    numbers_lost = False
    if slide_kind in _NUMBER_KINDS and n >= 1:
        holders = _number_holders(pattern, group)
        if n > holders:
            cap = 0.0
            kind *= 0.5
            numbers_lost = True
            reasons.append(f"числа не поместятся и будут потеряны: {n} чисел, мест {holders}")
    n_items = needed_items(slide)
    text_slots = [s for s in pattern.slots if s.role in (SlotRole.body, SlotRole.bullet_list, SlotRole.card_title, SlotRole.card_body, SlotRole.number, SlotRole.number_label, SlotRole.caption)]
    needed_slots = sum(1 for r in needed_roles if r not in ("title", "subtitle")) + max(n_items - 1, 0) * sum(1 for r in ("card_title", "card_body", "number", "number_label") if r in needed_roles)
    extra = max(len(text_slots) - max(needed_slots, 1), 0)
    clutter = min(0.3, 0.03 * extra)
    if clutter:
        reasons.append(f"{extra} лишних текстовых слотов останутся пустыми")
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
    # a pattern that needs the text shrunk ×1.8 renders tiny type: that outweighs an exact kind match
    if worst > 1.8:
        kind *= 0.6
    elif worst > 1.3:
        kind *= 0.85

    # family continuity
    fam = 1.0
    if slide.kind not in _STANDALONE_KINDS and prev_family is not None and pattern.family != prev_family:
        fam = 0.5
        reasons.append(f"семья {pattern.family.value} отличается от предыдущего слайда")

    diversity = -0.15 if pattern.id in recent_ids else 0.0
    if diversity:
        reasons.append("паттерн уже использован недавно")
    weight = strategy.weight(pattern.kind.value) if pattern.kind == slide.kind else 1.0
    if weight != 1.0:
        reasons.append(f"вес стратегии {strategy.name} для типа: ×{weight:.2f}")
    # a large sample image (photo, screenshot, chart picture) that the content cannot replace would stay as stale sample content
    has_visual = bool(content.image_hint or content.chart is not None or content.table is not None)
    stale_images = [s for s in pattern.slots if s.role == SlotRole.image and s.bbox.area >= 0.12]
    if stale_images and not has_visual:
        kind *= 0.6
        reasons.append("крупная картинка-образец останется без замены")
    # strategy flavour: visual favours decorated/illustrated samples, compact favours denser samples, structured plain ones
    n_decor = len(pattern.decor_assets) + sum(1 for s in pattern.slots if s.role in (SlotRole.icon, SlotRole.image))
    if strategy.name == "visual":
        style = 0.08 if n_decor >= 1 else 0.0
    elif strategy.name == "compact":
        style = 0.08 * min(len(text_slots) / 8.0, 1.0)
    else:
        style = 0.04 if n_decor == 0 else 0.0
    if style:
        reasons.append(f"стиль стратегии {strategy.name}: +{style:.2f}")
    # the strategy weight scales only the kind term, so it cannot lift a pattern with failed capacity above 1.0
    base = 0.45 * kind * weight + 0.25 * cap + 0.1 * text + 0.05 * fam + 0.1 * pattern.quality + diversity - clutter + style
    score = max(0.0, min(1.2, base))
    if numbers_lost and score >= strategy.synth_threshold:
        # losing a fact is worse than any synthesized stat row: such a pattern may stay an alternative but never wins over synth
        score = max(0.0, strategy.synth_threshold - 0.05)
        reasons.append(f"балл опущен ниже порога синтеза {strategy.synth_threshold:.2f}, чтобы не терять числа")
    return ScoreResult(round(score, 3), reasons, fit)
