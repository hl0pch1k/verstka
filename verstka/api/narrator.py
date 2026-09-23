"""Deterministic explanations for the chat helper: what the pipeline did and why, in plain Russian (no ids, no scores
that only the matcher understands)."""

from __future__ import annotations

from collections import Counter
from typing import Optional

from verstka.ru import TYPE_ROLE_RU, ru_count, ru_num
from verstka.schemas.audit import AuditReport
from verstka.schemas.layout import LayoutPlan
from verstka.schemas.outline import DeckOutline
from verstka.schemas.template import TemplateManifest

_KIND_RU = {
    "title": "титульный", "section": "разделитель", "agenda": "повестка", "bullets": "список", "cards": "карточки", "two_column": "две колонки",
    "big_number": "большая цифра", "stat_row": "ряд показателей", "comparison": "сравнение", "timeline": "таймлайн", "process": "шаги",
    "table": "таблица", "chart": "диаграмма", "image_text": "картинка и текст", "team": "команда", "quote": "цитата", "code": "код",
    "mockup": "мокап", "thanks": "финальный", "freeform": "свободный",
}


def kind_ru(kind: str) -> str:
    return _KIND_RU.get(kind, kind)


def describe_template(m: TemplateManifest) -> str:
    t = m.tokens
    kinds = Counter(p.kind.value for p in m.patterns)
    top = ", ".join(f"{kind_ru(k)} ×{v}" for k, v in kinds.most_common(6))
    fonts = [f.family for f in t.typography.families[:2]]
    accents = ", ".join("#" + a for a in t.accents()[:3])
    scale = ", ".join(f"{TYPE_ROLE_RU.get(s.role, s.role)} {ru_num(s.size_pt)} пт" for s in t.typography.scale)
    fam = Counter(p.family.value for p in m.patterns)
    dark = fam.get("dark", 0) > fam.get("light", 0)
    look = f"Оформление {'тёмное' if dark else 'светлое'}"
    if fonts:
        look += f", {'шрифт' if len(fonts) == 1 else 'шрифты'} {', '.join(fonts)}"
    if accents:
        look += f", акцентные цвета {accents}"
    usable = "все подходят" if len(m.patterns) >= m.n_slides else f"из них {ru_count(len(m.patterns), 'подходит', 'подходят', 'подходят')}"
    lines = [f"Разобрал шаблон «{m.source_file}»: {ru_count(m.n_slides, 'слайд', 'слайда', 'слайдов')}, {usable} как образцы для новых слайдов.", look + "."]
    if scale:
        lines.append(f"Размеры шрифтов: {scale}.")
    if top:
        lines.append(f"Какие слайды есть: {top}.")
    if t.chrome:
        lines.append("Логотип и колонтитулы шаблона сохраняются на каждом слайде.")
    if m.style_rules:
        rules = [r.text for r in m.style_rules if r.source != "derived"][:3]
        if rules:
            lines.append("Правила дизайнера из шаблона: " + " ".join(f"«{r}»" for r in rules))
    if m.warnings:
        lines.append(f"Не удалось разобрать: {ru_count(len(m.warnings), 'место', 'места', 'мест')} — подробности в «Что Verstka поняла из шаблона».")
    return "\n".join(lines)


def _match(score: float) -> str:
    return f"совпадение {max(0, min(100, round(score * 100)))}%"


def describe_plan(outline: DeckOutline, plan: LayoutPlan, manifest: TemplateManifest, strategy_title: str) -> str:
    patterns = {p.id: p for p in manifest.patterns}
    n_clone = sum(1 for s in plan.slides if s.mode == "clone" and s.pattern_id in patterns)
    n_synth = len(plan.slides) - n_clone
    head = f"Вариант «{strategy_title}»: {ru_count(len(outline.slides), 'слайд', 'слайда', 'слайдов')}"
    head += f" — {n_clone} по образцам слайдов шаблона" + (f", {n_synth} собраны с нуля в его стиле" if n_synth else "") + "."
    lines = [head]
    for i, osl in enumerate(outline.slides, 1):
        ps = plan.for_outline(osl.id)
        if ps is None:
            continue
        how = f"по образцу слайда {patterns[ps.pattern_id].source_slide}" if ps.mode == "clone" and ps.pattern_id in patterns else "собран с нуля"
        lines.append(f"{i}. {kind_ru(osl.kind.value).capitalize()}: «{osl.headline[:60]}» — {how}")
    return "\n".join(lines)


def describe_slide_choice(outline: DeckOutline, plan: LayoutPlan, manifest: TemplateManifest, index: int) -> str:
    if not (1 <= index <= len(outline.slides)):
        return f"В презентации {ru_count(len(outline.slides), 'слайд', 'слайда', 'слайдов')} — слайда {index} нет."
    osl = outline.slides[index - 1]
    ps = plan.for_outline(osl.id)
    if ps is None:
        return f"Для слайда {index} нет записи в плане."
    patterns = {p.id: p for p in manifest.patterns}
    head = f"Слайд {index} — {kind_ru(osl.kind.value)}: «{osl.headline}»."
    if ps.mode == "clone" and ps.pattern_id in patterns:
        p = patterns[ps.pattern_id]
        body = f"Собран по образцу слайда {p.source_slide} шаблона ({kind_ru(p.kind.value)}), {_match(ps.score)}."
        others = len({pid for pid, _ in ps.alternatives if pid != ps.pattern_id})
        if others:
            body += f" Подходили ещё {ru_count(others, 'макет', 'макета', 'макетов')}."
    else:
        body = "Подходящего образца в шаблоне не нашлось, поэтому слайд собран с нуля — в цветах, шрифтах и сетке шаблона."
    return f"{head} {body} Причины выбора — в панели «Почему этот слайд такой»."


FIX_RU = {
    "rematch": "подбор другого макета",
    "synth": "сборка слайда заново",
    "condense_text": "сокращение текста",
    "xml": "правка оформления",
    "rollback": "отмена неудачной правки",
}


def _check_titles() -> dict[str, str]:
    from verstka.audit.model_checks import DECK_COHERENCE, SLIDE_CONTENT
    from verstka.audit.registry import all_checks

    return {spec.id: spec.title for spec in [s for s, _ in all_checks()] + [SLIDE_CONTENT, DECK_COHERENCE]}


def describe_audit(report: AuditReport, check_titles: Optional[dict[str, str]] = None) -> str:
    """The audit in words a person reads: the score, problems by their titles (not check ids), what autofix did."""
    titles = check_titles if check_titles is not None else _check_titles()
    title = lambda cid: titles.get(cid, cid)  # noqa: E731
    s = report.summary
    if not report.issues:
        return "Проверка качества: 100 из 100, замечаний нет."
    errs = Counter(i.check_id for i in report.issues if i.severity == "error")
    warns = Counter(i.check_id for i in report.issues if i.severity == "warn")
    head = f"Проверка качества: {s.score:g} из 100, " + ("ошибок нет" if not s.errors else ru_count(s.errors, "ошибка", "ошибки", "ошибок"))
    if s.warnings:
        head += ", " + ru_count(s.warnings, "предупреждение", "предупреждения", "предупреждений")
    if s.model_flags:
        head += ", " + ru_count(s.model_flags, "замечание модели", "замечания модели", "замечаний модели")
    head += "."
    lines = [head]
    if errs:
        lines.append("Ошибки: " + "; ".join(f"{title(k)} ×{v}" if v > 1 else title(k) for k, v in errs.most_common()) + ".")
    if warns:
        lines.append("Предупреждения: " + "; ".join(f"{title(k)} ×{v}" if v > 1 else title(k) for k, v in warns.most_common(6)) + ".")
    if report.applied_fixes:
        fixes = Counter(f.get("action") for f in report.applied_fixes)
        passes = report.iterations
        lines.append(
            f"Уже исправлено автоматически ({ru_count(passes, 'проход', 'прохода', 'проходов')}): "
            + ", ".join(f"{FIX_RU.get(k, k)} ×{v}" if v > 1 else FIX_RU.get(k, k) for k, v in fixes.items()) + "."
        )
    fixable = [i for i in report.issues if i.autofix and i.autofix.action != "none"]
    if fixable:
        lines.append(f"Ещё {len(fixable)} можно исправить автоматически: скажите «исправь всё» или нажмите «Исправить всё автоматически» в «Проверке качества».")
    return "\n".join(lines)
