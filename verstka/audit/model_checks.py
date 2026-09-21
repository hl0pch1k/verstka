"""Non-deterministic checks: VLM slide content audit (11 questions) and LLM deck coherence."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from verstka.analysis.classify import image_bytes_for_vlm
from verstka.audit.registry import AuditContext
from verstka.providers.base import ProviderError
from verstka.providers.registry import ProviderRegistry
from verstka.schemas.audit import CheckSpec, Issue
from verstka.skills_registry.registry import SkillsRegistry

log = logging.getLogger(__name__)

CONTENT_QUESTIONS = {
    1: "Заголовок содержит вывод, а не просто называет тему?",
    2: "Содержимое слайда соответствует заголовку?",
    3: "Слайд пересказывается одним предложением?",
    4: "Все цифры и факты со слайда есть в исходных материалах?",
    5: "На слайде есть содержание, а не только заголовок?",
    6: "Картинки и иконки относятся к теме слайда?",
    7: "Нет служебного мусора: реплик спикера, кусков промпта?",
    8: "Текст без опечаток?",
    9: "Вся колода на одном языке?",
    10: "Все строки таблицы и элементы легенды работают на мысль слайда?",
    11: "Соседние слайды связаны между собой по логике?",
}

SLIDE_CONTENT = CheckSpec(id="slide_content", title="Валидация контента слайда (VLM)", severity="warn", kind="model", category="content", description="11 вопросов из приложения к ТЗ, ответ да/нет по картинке слайда и плану.")
DECK_COHERENCE = CheckSpec(id="deck_coherence", title="Связность колоды (LLM)", severity="warn", kind="model", category="content", description="Логика переходов между соседними слайдами и единый язык колоды.")


class ContentAnswer(BaseModel):
    question: int
    ok: bool
    evidence: str = ""


class ContentAudit(BaseModel):
    """Output of the `slide_content_audit` skill."""

    answers: list[ContentAnswer] = Field(default_factory=list)


class CoherenceIssue(BaseModel):
    slide: int
    text: str


class CoherenceAudit(BaseModel):
    """Output of the `deck_coherence_audit` skill."""

    issues: list[CoherenceIssue] = Field(default_factory=list)
    language_ok: bool = True


def run_model_checks(ctx: AuditContext, skills: SkillsRegistry, providers: ProviderRegistry, use_vlm: bool = True, use_llm: bool = True, max_workers: int = 4) -> tuple[list[Issue], list[str]]:
    issues: list[Issue] = []
    warnings: list[str] = []
    outline = ctx.outline
    facts_json = json.dumps([f.model_dump() for f in outline.facts], ensure_ascii=False) if outline else "[]"

    def slide_task(s):
        img = ctx.slide_images.get(s.index)
        if img is None or not Path(img).exists():
            return s.index, None, "no image"
        osl = next((o for o in outline.slides if o.id == s.outline_id), None) if outline and s.outline_id else None
        try:
            res = skills.run(
                "slide_content_audit",
                providers,
                {
                    "slide_index": s.index,
                    "headline": osl.headline if osl else "",
                    "slide_text": "\n".join(e.text for e in s.texts)[:2000],
                    "outline_json": osl.model_dump_json() if osl else "{}",
                    "facts_json": facts_json,
                    "questions": "\n".join(f"{k}. {v}" for k, v in CONTENT_QUESTIONS.items()),
                },
                images=[image_bytes_for_vlm(Path(img))],
            )
            return s.index, res.parsed, None
        except (ProviderError, ValueError, KeyError) as e:
            return s.index, None, str(e)[:160]

    if use_vlm and providers.has("vlm"):
        with ThreadPoolExecutor(max_workers=min(max_workers, providers.limits.max_concurrency)) as ex:
            for idx, parsed, err in ex.map(slide_task, ctx.ir.slides):
                if err:
                    warnings.append(f"slide {idx}: content audit skipped: {err}")
                    continue
                for a in parsed.answers:
                    if not a.ok and a.question in CONTENT_QUESTIONS:
                        sev = "error" if a.question in (4, 7) else "warn"
                        issues.append(ctx.new_issue(SLIDE_CONTENT, idx, f"{CONTENT_QUESTIONS[a.question]} — нет. {a.evidence}".strip(), severity=sev, details={"question": a.question}))
    if use_llm and providers.has("llm") and ctx.ir.slides:
        try:
            seq = [{"slide": s.index, "headline": (next((o.headline for o in outline.slides if o.id == s.outline_id), "") if outline and s.outline_id else ""), "text": " ".join(e.text for e in s.texts)[:300]} for s in ctx.ir.slides]
            res = skills.run("deck_coherence_audit", providers, {"sequence_json": json.dumps(seq, ensure_ascii=False)})
            coh: CoherenceAudit = res.parsed
            for it in coh.issues:
                issues.append(ctx.new_issue(DECK_COHERENCE, it.slide, it.text, details={"question": 11}))
            if not coh.language_ok:
                issues.append(ctx.new_issue(DECK_COHERENCE, 0, "колода не на одном языке", details={"question": 9}))
        except (ProviderError, ValueError, KeyError) as e:
            warnings.append(f"coherence audit skipped: {str(e)[:160]}")
    return issues, warnings
