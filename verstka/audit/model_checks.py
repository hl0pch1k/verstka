"""Non-deterministic checks: VLM slide content audit (11 questions) and LLM deck coherence."""

from __future__ import annotations

import json
import re
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

SLIDE_CONTENT = CheckSpec(id="slide_content", title="Валидация контента слайда (VLM)", severity="warn", kind="model", category="content", description="11 вопросов из приложения к ТЗ, ответ да/нет по картинке готового слайда и плану. Идёт по умолчанию вместе с моделью текста (CLI `--no-audit-models`, API `audit_models: false` — выключить) один раз на готовой колоде, после автоисправления, в пределах 5 минут сборки. Вес ответа «нет»: служебный мусор (7) и цифра не из источников (4) — ошибка; несоответствие заголовку, пустой слайд, картинка не к теме, опечатки, смесь языков — предупреждение; заголовок без вывода, несколько мыслей, лишняя строка легенды — сведение. Обложке, разделу и финалу вопросы 1, 2, 3, 5, 10 не задаются; вопрос 4 не задаётся, когда все цифры колоды сверены с текстом и данными правилами.")
DECK_COHERENCE = CheckSpec(id="deck_coherence", title="Связность колоды (LLM)", severity="warn", kind="model", category="content", description="Логика переходов между соседними слайдами (сведение) и единый язык колоды (предупреждение); идёт вместе с `slide_content`.")


# the questions a cover, a section divider, an agenda or a closing slide answers «no» to by design (no conclusion in
# its heading, no content under it, nothing to retell): the live run of 20.10 flagged every cover with them
FRAME_SKIPS = {1, 2, 3, 5, 10}
# how much a «no» weighs: garbage on the slide and a figure not in the sources are errors; a heading without a conclusion,
# a slide with more than one idea, a legend row off the point, a weak link between slides are advice (a model's reading,
# on by default since 20.10: it never sinks a deck the rules found clean)
QUESTION_SEVERITY = {1: "info", 2: "warn", 3: "info", 4: "error", 5: "warn", 6: "warn", 7: "error", 8: "warn", 9: "warn", 10: "info", 11: "info"}
_FRAME_KINDS = {"title", "section", "agenda", "thanks"}


def _frame_slide(ctx: AuditContext, idx: int) -> bool:
    if ctx.outline is None or not 1 <= idx <= len(ctx.ir.slides):
        return idx == 1
    oid = ctx.ir.slides[idx - 1].outline_id
    osl = next((o for o in ctx.outline.slides if o.id == oid), None) if oid else None
    if osl is None:
        return idx == 1
    return getattr(osl.kind, "value", osl.kind) in _FRAME_KINDS


# what the model calls the template's own marks when it takes them for garbage (jury 20.10: the VK Tech logo «tech»
# called «служебный мусор» — an error that sank a good deck to 62)
_CHROME_WORDS_RE = re.compile(r"логотип|logo|колонтитул|номер слайда|нумераци|водян|эмблем|фирменн|декоративн|элемент оформления|рамк[аи] шаблона", re.I)


def _chrome_texts(ctx: AuditContext) -> dict[int, list[str]]:
    """Slide → the texts of the template's chrome on it (page number, footer, logo text, marks where the analysis found
    chrome)."""
    from verstka.audit.checks.common import is_chrome_like, is_template_chrome

    out: dict[int, list[str]] = {}
    for s in ctx.ir.slides:
        for e in s.elements:
            t = (getattr(e, "text", "") or "").strip()
            if not t:
                continue
            try:
                chrome = is_template_chrome(e, ctx.manifest) or is_chrome_like(e, ctx.ir, ctx.manifest)
            except Exception:  # noqa: BLE001 - not known as chrome
                chrome = False
            if chrome:
                out.setdefault(s.index, []).append(t)
    return out


def _about_chrome(evidence: str, chrome: list[str]) -> bool:
    """The model's «no» speaks of the template's own marks: it names a logo, a footer, a page number — or quotes a text of
    the slide's chrome («tech»)."""
    ev = (evidence or "").strip()
    if not ev:
        return False
    if _CHROME_WORDS_RE.search(ev):
        return True
    low = ev.lower()
    return any(len(t) >= 2 and (f"«{t.lower()}»" in low or f'"{t.lower()}"' in low) for t in chrome)


def model_check_specs() -> tuple[CheckSpec, ...]:
    """Every model check the audit can report: the content audit, the deck's coherence and «Взгляд дизайнера»."""
    from verstka.audit.eyes import DESIGN_REVIEW

    return (SLIDE_CONTENT, DECK_COHERENCE, DESIGN_REVIEW)


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

    figures_checked = bool(getattr(ctx, "figure_stats", None) and (ctx.figure_stats or {}).get("checked"))
    chrome_texts = _chrome_texts(ctx)
    if use_vlm and providers.has("vlm"):
        with ThreadPoolExecutor(max_workers=min(max_workers, providers.limits.max_concurrency)) as ex:
            for idx, parsed, err in ex.map(slide_task, ctx.ir.slides):
                if err:
                    warnings.append(f"slide {idx}: content audit skipped: {err}")
                    continue
                frame = _frame_slide(ctx, idx)
                for a in parsed.answers:
                    if frame and a.question in FRAME_SKIPS:
                        continue  # a cover, a divider, a closing slide names its topic and carries no content: by design
                    if a.question == 4 and figures_checked:
                        continue  # every figure of the deck was checked against the brief and the data by the rules
                    if not a.ok and a.question in (7, 8) and _about_chrome(a.evidence, chrome_texts.get(idx, [])):
                        continue  # the template's logo, page number, footer or ornament: its design, never garbage
                    if not a.ok and a.question in CONTENT_QUESTIONS:
                        sev = QUESTION_SEVERITY.get(a.question, "warn")
                        issues.append(ctx.new_issue(SLIDE_CONTENT, idx, f"{CONTENT_QUESTIONS[a.question]} — нет. {a.evidence}".strip(), severity=sev, details={"question": a.question}))
    if use_llm and providers.has("llm") and ctx.ir.slides:
        try:
            seq = [{"slide": s.index, "headline": (next((o.headline for o in outline.slides if o.id == s.outline_id), "") if outline and s.outline_id else ""), "text": " ".join(e.text for e in s.texts)[:300]} for s in ctx.ir.slides]
            res = skills.run("deck_coherence_audit", providers, {"sequence_json": json.dumps(seq, ensure_ascii=False)})
            coh: CoherenceAudit = res.parsed
            for it in coh.issues:
                issues.append(ctx.new_issue(DECK_COHERENCE, it.slide, it.text, severity="info", details={"question": 11}))
            if not coh.language_ok:
                issues.append(ctx.new_issue(DECK_COHERENCE, 0, "колода не на одном языке", details={"question": 9}))
        except (ProviderError, ValueError, KeyError) as e:
            warnings.append(f"coherence audit skipped: {str(e)[:160]}")
    return issues, warnings
