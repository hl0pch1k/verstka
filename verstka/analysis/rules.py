"""Style rules: derived from statistics and harvested from designer notes written on template slides."""

from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from verstka.providers.base import ProviderError
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.template import StyleRule, Tokens
from verstka.skills_registry.registry import SkillsRegistry

log = logging.getLogger(__name__)

_INSTRUCTION_RE = re.compile(
    r"(использу|выравнива|шрифт|цвет|кегл|не (используй|ставь|добавляй)|можно|нужно|следует|избега|удаля|делаем|берём|берем|"
    r"оформл|отступ|иконк|таблиц|диаграмм|график|логотип|заголовк|буллит|буллет|навигац|разделител|легенд|сетк|"
    r"use |avoid|align|font|color|colour|should|must|never|always)",
    re.I,
)


class RuleItem(BaseModel):
    text: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class RuleHarvest(BaseModel):
    """Output of the `rule_harvester` skill."""

    rules: list[RuleItem] = Field(default_factory=list)


def instruction_candidates(slide_texts: list[str], min_len: int = 25, max_len: int = 400) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for text in slide_texts:
        for para in re.split(r"[\n\r]+", text):
            p = para.strip()
            if min_len <= len(p) <= max_len and _INSTRUCTION_RE.search(p) and p.lower() not in seen:
                seen.add(p.lower())
                out.append(p)
    return out


def derived_rules(tokens: Tokens) -> list[StyleRule]:
    rules: list[StyleRule] = []
    typo = tokens.typography
    if typo.families:
        main = [f.family for f in typo.families if f.weight >= 0.05][:2] or [typo.families[0].family]
        rules.append(StyleRule(text=f"Шрифты шаблона: {', '.join(main)}. Другие гарнитуры не использовать.", source="derived"))
    if typo.left_align_share >= 0.8:
        rules.append(StyleRule(text="Текст выравнивается по левому краю (исключения: схемы и таблицы).", source="derived", confidence=round(typo.left_align_share, 2)))
    elif typo.left_align_share <= 0.4:
        rules.append(StyleRule(text="Текст в шаблоне преимущественно центрирован.", source="derived", confidence=round(1 - typo.left_align_share, 2)))
    if typo.scale:
        steps = ", ".join(f"{s.role} {s.size_pt:g} pt" for s in typo.scale)
        rules.append(StyleRule(text=f"Шкала кеглей: {steps}. Кегли вне шкалы не использовать.", source="derived"))
    accents = tokens.accents()
    if accents:
        rules.append(StyleRule(text=f"Акцентные цвета по приоритету: {', '.join('#' + a for a in accents)}.", source="derived"))
    tp = tokens.color_for("text.primary")
    if tp:
        rules.append(StyleRule(text=f"Основной цвет текста #{tp}.", source="derived"))
    if tokens.shapes.corner_radius_share >= 0.6 and tokens.shapes.typical_radius:
        rules.append(StyleRule(text="Карточки и блоки со скруглёнными углами.", source="derived", confidence=round(tokens.shapes.corner_radius_share, 2)))
    if tokens.shapes.shadow_share <= 0.05:
        rules.append(StyleRule(text="Тени не используются; границы блоков задаются заливкой или тонким контуром.", source="derived", confidence=0.7))
    return rules


def harvest_rules(
    slide_texts: list[str],
    tokens: Tokens,
    skills: Optional[SkillsRegistry] = None,
    providers: Optional[ProviderRegistry] = None,
    use_llm: bool = True,
) -> tuple[list[StyleRule], list[str]]:
    warnings: list[str] = []
    rules = derived_rules(tokens)
    candidates = instruction_candidates(slide_texts)
    if use_llm and candidates and skills is not None and providers is not None and providers.has("llm"):
        try:
            res = skills.run("rule_harvester", providers, {"candidates": "\n".join(f"- {c}" for c in candidates[:80])})
            harvest: RuleHarvest = res.parsed
            for r in harvest.rules:
                if r.text.strip():
                    rules.append(StyleRule(text=r.text.strip(), source="llm", confidence=r.confidence))
        except (ProviderError, ValueError) as e:
            warnings.append(f"rule harvesting failed: {str(e)[:200]}")
            for c in candidates[:20]:
                rules.append(StyleRule(text=c, source="template_text", confidence=0.5))
    else:
        for c in candidates[:20]:
            rules.append(StyleRule(text=c, source="template_text", confidence=0.5))
    return rules, warnings
