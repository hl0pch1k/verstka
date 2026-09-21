"""Deterministic explanations for the chat agent: what the pipeline did and why (Russian)."""

from __future__ import annotations

from collections import Counter
from typing import Optional

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
    fonts = ", ".join(f.family for f in t.typography.families[:2]) or "не определены"
    accents = ", ".join("#" + a for a in t.accents()[:3]) or "не найдены"
    scale = ", ".join(f"{s.role} {s.size_pt:g}" for s in t.typography.scale)
    fam = Counter(p.family.value for p in m.patterns)
    family_txt = "тёмная" if fam.get("dark", 0) > fam.get("light", 0) else "светлая"
    lines = [
        f"Разобрал шаблон «{m.source_file}»: {m.n_slides} слайдов, {len(m.patterns)} паттернов, {len(m.assets)} ассетов, {len(t.chrome)} элементов хрома (логотипы, колонтитулы, узоры).",
        f"Дизайн-система: основная семья {family_txt}, шрифты {fonts}, акценты {accents}, шкала кеглей {scale}.",
        f"Типы слайдов: {top}.",
    ]
    if m.style_rules:
        rules = [r.text for r in m.style_rules if r.source != "derived"][:3]
        if rules:
            lines.append("Правила дизайнера из шаблона: " + " ".join(f"«{r}»" for r in rules))
    if m.warnings:
        lines.append(f"Предупреждений при разборе: {len(m.warnings)}.")
    return "\n".join(lines)


def describe_plan(outline: DeckOutline, plan: LayoutPlan, manifest: TemplateManifest, strategy_title: str) -> str:
    patterns = {p.id: p for p in manifest.patterns}
    n_clone = sum(1 for s in plan.slides if s.mode == "clone")
    n_synth = len(plan.slides) - n_clone
    lines = [f"Вариант «{strategy_title}»: {len(outline.slides)} слайдов, {n_clone} собраны на образцах шаблона, {n_synth} синтезированы из его дизайн-токенов."]
    for osl in outline.slides:
        ps = plan.for_outline(osl.id)
        if ps is None:
            continue
        if ps.mode == "clone" and ps.pattern_id in patterns:
            p = patterns[ps.pattern_id]
            why = next((r for r in ps.reasons if "ёмкост" in r or "ячеек" in r or "помещ" in r), "")
            lines.append(f"{osl.id[2:] if osl.id.startswith('sl') else osl.id}. {kind_ru(osl.kind.value)} «{osl.headline[:60]}» → слайд {p.source_slide} шаблона ({kind_ru(p.kind.value)}), балл {ps.score:.2f}{'; ' + why if why else ''}.")
        else:
            lines.append(f"{osl.id[2:] if osl.id.startswith('sl') else osl.id}. {kind_ru(osl.kind.value)} «{osl.headline[:60]}» → композиция «{ps.composition}» из токенов: {ps.reasons[0] if ps.reasons else ''}.")
    return "\n".join(lines)


def describe_slide_choice(outline: DeckOutline, plan: LayoutPlan, manifest: TemplateManifest, index: int) -> str:
    if not (1 <= index <= len(outline.slides)):
        return f"В колоде {len(outline.slides)} слайдов."
    osl = outline.slides[index - 1]
    ps = plan.for_outline(osl.id)
    if ps is None:
        return "Для этого слайда нет записи в плане."
    patterns = {p.id: p for p in manifest.patterns}
    head = f"Слайд {index} ({kind_ru(osl.kind.value)}): «{osl.headline}»."
    if ps.mode == "clone" and ps.pattern_id in patterns:
        p = patterns[ps.pattern_id]
        body = f"Взят слайд {p.source_slide} шаблона (тип {kind_ru(p.kind.value)}, балл {ps.score:.2f}). Причины: " + "; ".join(ps.reasons[1:6]) + "."
    else:
        body = f"Синтезирован как «{ps.composition}»: " + "; ".join(ps.reasons[:3]) + "."
    alts = ", ".join(f"{pid} ({sc:.2f})" for pid, sc in ps.alternatives[:3])
    if alts:
        body += f" Запасные варианты: {alts}."
    return head + " " + body


def describe_audit(report: AuditReport) -> str:
    s = report.summary
    if not report.issues:
        return "Аудит: замечаний нет, оценка 100."
    by_check = Counter(i.check_id for i in report.issues if i.severity == "error")
    warn_by = Counter(i.check_id for i in report.issues if i.severity == "warn")
    lines = [f"Аудит: оценка {s.score}, ошибок {s.errors}, предупреждений {s.warnings}, замечаний модели {s.model_flags}."]
    if by_check:
        lines.append("Ошибки: " + ", ".join(f"{k} ×{v}" for k, v in by_check.most_common()) + ".")
    if warn_by:
        lines.append("Предупреждения: " + ", ".join(f"{k} ×{v}" for k, v in warn_by.most_common(6)) + ".")
    if report.applied_fixes:
        fixes = Counter(f.get("action") for f in report.applied_fixes)
        lines.append(f"Автофикс за {report.iterations} итерац.: " + ", ".join(f"{k} ×{v}" for k, v in fixes.items()) + ".")
    fixable = [i for i in report.issues if i.autofix and i.autofix.action != "none"]
    if fixable:
        lines.append(f"{len(fixable)} замечаний можно исправить автоматически — отметьте нужные в панели аудита.")
    return "\n".join(lines)
