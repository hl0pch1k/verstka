"""Integrity checks: file opens, empty deck, placeholders, empty/picture slides, lost content, chart labels, duplicates."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from verstka.analysis.shapes import looks_like_placeholder
from verstka.audit.checks.common import content_elements, fix, text_elements, title_element
from verstka.audit.registry import AuditContext, check
from verstka.schemas.audit import CheckSpec, Issue
from verstka.schemas.deck_ir import IRSlide
from verstka.schemas.outline import OutlineSlide

FILE_OPENS = CheckSpec(id="file_opens", title="Файл не открывается", severity="error", category="integrity", description="PPTX не открывается python-pptx или не рендерится LibreOffice.")
EMPTY_DECK = CheckSpec(id="empty_deck", title="В колоде нет ни одного слайда", severity="error", category="integrity", description="Файл открывается, но не содержит слайдов.")
PLACEHOLDER_TEXT = CheckSpec(id="placeholder_text", title="Остался текст-заглушка", severity="error", category="integrity", description="На слайде остался lorem ipsum, XXX, TODO, «вставьте текст», «Заголовок», «Имя Фамилия» и подобные заглушки шаблона.")
EMPTY_SLIDE = CheckSpec(id="empty_slide", title="Пустой слайд или слайд с одним заголовком", severity="error", category="integrity", description="На слайде нет контента кроме заголовка (кроме титульного, разделителей и финального).")
SLIDE_IS_PICTURE = CheckSpec(id="slide_is_picture", title="Слайд оказался картинкой, а не редактируемыми объектами", severity="error", category="integrity", description="Одна картинка занимает ≥ 90% слайда и на слайде нет текста.")
CHART_MISSING_LABELS = CheckSpec(id="chart_missing_labels", title="У диаграммы нет подписей осей, единиц или легенды", severity="warn", category="integrity", description="Нативная диаграмма без подписей данных и без оси значений, либо многосерийная без легенды, либо без единиц измерения.")
DUPLICATE_SLIDES = CheckSpec(id="duplicate_slides", title="Два слайда дублируют друг друга", severity="warn", category="integrity", description="Текст двух слайдов совпадает более чем на 90%.")
CONTENT_MISSING = CheckSpec(id="content_missing", title="Часть запланированного контента пропала со слайда", severity="error", category="integrity", description="Заголовок, пункты списков, названия карточек, числа с подписями и заголовки колонок из плана ищутся в тексте слайда (включая ячейки таблиц) без учёта пробелов и регистра по первым 18 символам; ошибка, если нет трети и более строк, иначе предупреждение.")

CONTENT_KEY_CHARS = 18
_WS_RE = re.compile(r"[\s\u00a0\u202f\u2009\u2007\u2060]+")


@check(FILE_OPENS)
def file_opens(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    if not ctx.opens_ok:
        out.append(ctx.new_issue(FILE_OPENS, 0, "файл не открывается python-pptx"))
    if ctx.render_ok is False:
        out.append(ctx.new_issue(FILE_OPENS, 0, "LibreOffice не смог отрендерить файл", severity="warn"))
    return out


@check(EMPTY_DECK)
def empty_deck(ctx: AuditContext) -> list[Issue]:
    if ctx.opens_ok and not ctx.ir.slides:
        return [ctx.new_issue(EMPTY_DECK, 0, "в колоде нет ни одного слайда")]
    return []


@check(PLACEHOLDER_TEXT)
def placeholder_text(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        for e in s.elements:  # table cells included: sample tables keep their placeholder text too
            if not e.has_text:
                continue
            t = e.text.strip()
            if looks_like_placeholder(t):
                out.append(ctx.new_issue(PLACEHOLDER_TEXT, s.index, f"заглушка «{t[:40]}»", bboxes=[e.bbox_frac], element_ids=[e.id], autofix=fix("drop_element", "удалить заглушку", element_id=e.id)))
    return out


def _outline_slide(ctx: AuditContext, s: IRSlide) -> Optional[OutlineSlide]:
    if ctx.outline is None or not s.outline_id:
        return None
    return next((o for o in ctx.outline.slides if o.id == s.outline_id), None)


@check(EMPTY_SLIDE)
def empty_slide(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    n = len(ctx.ir.slides)
    for s in ctx.ir.slides:
        if s.index in (1, n):
            continue
        els = content_elements(s, ctx.ir, ctx.manifest)
        title = title_element(s)
        others = [e for e in els if e is not title]
        text_others = [e for e in others if e.has_text or e.type in ("chart", "table")]
        osl = _outline_slide(ctx, s)
        # a picture is content only when the plan asked for one; otherwise it is template decoration next to a lone title
        picture_planned = osl is None or bool(osl.content.image_hint) or osl.kind.value == "image_text"
        has_picture = picture_planned and any(e.type == "picture" and e.bbox_frac.area > 0.1 for e in others)
        if not els or (title is not None and not text_others and not has_picture):
            kind = osl.kind.value if osl is not None else "unknown"
            if kind in ("section", "thanks", "title", "quote"):
                continue
            out.append(ctx.new_issue(EMPTY_SLIDE, s.index, "на слайде только заголовок", autofix=fix("rematch", "перевыбрать макет", outline_id=s.outline_id)))
    return out


def _norm_text(t: str) -> str:
    return _WS_RE.sub("", t).lower().replace("ё", "е")


def wanted_strings(osl: OutlineSlide) -> list[str]:
    """Texts the plan puts on the slide that must survive rendering (order preserved, duplicates dropped)."""
    c = osl.content
    raw: list[str] = [osl.headline]
    raw.extend(c.bullets)
    raw.extend(it.title for it in c.items)
    for n in c.numbers:
        raw.extend((n.value, n.label))
    raw.extend(col.title for col in c.columns)
    if c.table:
        raw.extend(c.table.columns)
    out: list[str] = []
    for t in raw:
        t = (t or "").strip()
        if t and _norm_text(t) and t not in out:
            out.append(t)
    return out


def _present(wanted: str, have: str) -> bool:
    """The planned line is on the slide: verbatim (by its first characters); as a cover's title and subtitle («Итоги
    пилота: план на 2027 год» set as «Итоги пилота» over «План на 2027 год»); or as a callout — a line that carries
    one figure («Средний чек — 300 рублей») set as its figure large and its words under it («300 ₽» over «Средний
    чек»), as the visual variant presents a chart's side lines."""
    if _norm_text(wanted)[:CONTENT_KEY_CHARS] in have:
        return True
    from verstka.matching.scorer import split_display_title
    from verstka.rendering.compose import kpi_callout

    head, tail = split_display_title(wanted)
    if tail and _norm_text(head)[:CONTENT_KEY_CHARS] in have and _norm_text(tail)[:CONTENT_KEY_CHARS] in have:
        return True  # a cover heading of two phrases set as a title and its subtitle

    got = kpi_callout(wanted)
    if got is None:
        return False
    value, label = got
    return _norm_text(label)[:CONTENT_KEY_CHARS] in have and _norm_text(value) in have


def slide_text_norm(s: IRSlide) -> str:
    parts = [e.text for e in s.elements if e.type == "text" and e.has_text]
    for e in s.elements:
        if e.type == "table" and e.table:
            parts.extend(cell for row in e.table.rows for cell in row)
    return "|".join(_norm_text(p) for p in parts)


@check(CONTENT_MISSING)
def content_missing(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        osl = _outline_slide(ctx, s)
        if osl is None:
            continue
        wanted = wanted_strings(osl)
        if not wanted:
            continue
        have = slide_text_norm(s)
        missing = [w for w in wanted if not _present(w, have)]
        if not missing:
            continue
        severity = "error" if len(missing) * 3 >= len(wanted) else "warn"
        shown = ", ".join(f"«{m[:40]}»" for m in missing[:3]) + ("…" if len(missing) > 3 else "")
        out.append(ctx.new_issue(CONTENT_MISSING, s.index, f"{len(missing)} из {len(wanted)} {'текста' if len(wanted) % 10 == 1 and len(wanted) % 100 != 11 else 'текстов'} плана нет на слайде: {shown}", severity=severity, details={"missing": missing, "wanted": len(wanted)}, autofix=fix("rematch", "перевыбрать макет, чтобы весь контент поместился", outline_id=s.outline_id)))
    return out


@check(SLIDE_IS_PICTURE)
def slide_is_picture(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        pics = [e for e in s.elements if e.type == "picture" and e.bbox_frac.area >= 0.9]
        if pics and not text_elements(s):
            out.append(ctx.new_issue(SLIDE_IS_PICTURE, s.index, "слайд состоит из одной картинки", bboxes=[pics[0].bbox_frac], element_ids=[pics[0].id]))
    return out


@check(CHART_MISSING_LABELS)
def chart_missing_labels(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        for e in s.elements:
            if e.type != "chart" or not e.chart:
                continue
            c = e.chart
            problems = []
            if not c.has_data_labels and not c.has_value_axis:
                problems.append("нет ни подписей данных, ни оси значений")
            if len(c.series) > 1 and not (c.has_legend or c.series_labels):  # series named on their labels need no legend
                problems.append("несколько серий без легенды")
            fmt = c.number_format or ""
            has_unit = any(ch in fmt for ch in "%₽$") or '"' in fmt
            if not has_unit and c.has_data_labels:
                problems.append("единицы измерения не указаны в подписях")
            if problems:
                out.append(ctx.new_issue(CHART_MISSING_LABELS, s.index, "; ".join(problems), bboxes=[e.bbox_frac], element_ids=[e.id], severity="info" if problems == ["единицы измерения не указаны в подписях"] else "warn"))
    return out


@check(DUPLICATE_SLIDES)
def duplicate_slides(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    texts = [(s.index, " ".join(e.text for e in s.elements if e.has_text).strip().lower()) for s in ctx.ir.slides]
    for i, (ia, ta) in enumerate(texts):
        if len(ta) < 40:
            continue
        for ib, tb in texts[i + 1 :]:
            if len(tb) < 40:
                continue
            if SequenceMatcher(None, ta, tb).ratio() > 0.9:
                out.append(ctx.new_issue(DUPLICATE_SLIDES, ib, f"слайд {ib} повторяет слайд {ia}", details={"other": ia}))
    return out
