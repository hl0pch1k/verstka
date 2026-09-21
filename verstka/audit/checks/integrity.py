"""Integrity checks: file opens, placeholders, empty/picture slides, chart labels, duplicates."""

from __future__ import annotations

from difflib import SequenceMatcher

from verstka.analysis.shapes import looks_like_placeholder
from verstka.audit.checks.common import content_elements, fix, title_element
from verstka.audit.registry import AuditContext, check
from verstka.schemas.audit import CheckSpec, Issue

FILE_OPENS = CheckSpec(id="file_opens", title="Файл не открывается", severity="error", category="integrity", description="PPTX не открывается python-pptx или не рендерится LibreOffice.")
PLACEHOLDER_TEXT = CheckSpec(id="placeholder_text", title="Остался текст-заглушка", severity="error", category="integrity", description="На слайде остался lorem ipsum, XXX, TODO, «вставьте текст», «Заголовок», «Имя Фамилия» и подобные заглушки шаблона.")
EMPTY_SLIDE = CheckSpec(id="empty_slide", title="Пустой слайд или слайд с одним заголовком", severity="error", category="integrity", description="На слайде нет контента кроме заголовка (кроме титульного, разделителей и финального).")
SLIDE_IS_PICTURE = CheckSpec(id="slide_is_picture", title="Слайд оказался картинкой, а не редактируемыми объектами", severity="error", category="integrity", description="Одна картинка занимает ≥ 90% слайда и на слайде нет текста.")
CHART_MISSING_LABELS = CheckSpec(id="chart_missing_labels", title="У диаграммы нет подписей осей, единиц или легенды", severity="warn", category="integrity", description="Нативная диаграмма без подписей данных и без оси значений, либо многосерийная без легенды, либо без единиц измерения.")
DUPLICATE_SLIDES = CheckSpec(id="duplicate_slides", title="Два слайда дублируют друг друга", severity="warn", category="integrity", description="Текст двух слайдов совпадает более чем на 90%.")


@check(FILE_OPENS)
def file_opens(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    if not ctx.opens_ok:
        out.append(ctx.new_issue(FILE_OPENS, 0, "файл не открывается python-pptx"))
    if ctx.render_ok is False:
        out.append(ctx.new_issue(FILE_OPENS, 0, "LibreOffice не смог отрендерить файл", severity="warn"))
    return out


@check(PLACEHOLDER_TEXT)
def placeholder_text(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        for e in s.texts:
            t = e.text.strip()
            if looks_like_placeholder(t):
                out.append(ctx.new_issue(PLACEHOLDER_TEXT, s.index, f"заглушка «{t[:40]}»", bboxes=[e.bbox_frac], element_ids=[e.id], autofix=fix("drop_element", "удалить заглушку", element_id=e.id)))
    return out


@check(EMPTY_SLIDE)
def empty_slide(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    n = len(ctx.ir.slides)
    for s in ctx.ir.slides:
        if s.index in (1, n):
            continue
        els = content_elements(s, ctx.ir)
        title = title_element(s)
        others = [e for e in els if e is not title]
        text_others = [e for e in others if e.has_text or e.type in ("chart", "table")]
        if not els or (title is not None and not text_others and not any(e.type == "picture" and e.bbox_frac.area > 0.1 for e in others)):
            kind = "unknown"
            if ctx.outline and s.outline_id:
                osl = next((o for o in ctx.outline.slides if o.id == s.outline_id), None)
                if osl is not None:
                    kind = osl.kind.value
            if kind in ("section", "thanks", "title", "quote"):
                continue
            out.append(ctx.new_issue(EMPTY_SLIDE, s.index, "на слайде только заголовок", autofix=fix("rematch", "перевыбрать макет", outline_id=s.outline_id)))
    return out


@check(SLIDE_IS_PICTURE)
def slide_is_picture(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        pics = [e for e in s.elements if e.type == "picture" and e.bbox_frac.area >= 0.9]
        if pics and not s.texts:
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
            if len(c.series) > 1 and not c.has_legend:
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
    texts = [(s.index, " ".join(e.text for e in s.texts).strip().lower()) for s in ctx.ir.slides]
    for i, (ia, ta) in enumerate(texts):
        if len(ta) < 40:
            continue
        for ib, tb in texts[i + 1 :]:
            if len(tb) < 40:
                continue
            if SequenceMatcher(None, ta, tb).ratio() > 0.9:
                out.append(ctx.new_issue(DUPLICATE_SLIDES, ib, f"слайд {ib} повторяет слайд {ia}", details={"other": ia}))
    return out
