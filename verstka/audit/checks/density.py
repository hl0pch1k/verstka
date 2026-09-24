"""Density checks: bullets, words, tables, series, fill ratio."""

from __future__ import annotations

from verstka.audit.checks.common import content_elements, fix, ru_count, text_elements, text_height_needed_pt
from verstka.audit.registry import AuditContext, check
from verstka.schemas.audit import CheckSpec, Issue
from verstka.schemas.common import EMU_PER_PT, Bbox

TOO_MANY_BULLETS = CheckSpec(id="too_many_bullets", title="Больше 6 пунктов в одном списке", severity="warn", category="density", description="В одном текстовом блоке больше шести пунктов списка.")
BULLET_TOO_LONG = CheckSpec(id="bullet_too_long", title="Пункт списка длиннее 15 слов", severity="warn", category="density", description="Пункт списка (абзац с маркером) содержит больше 15 слов.")
TABLE_TOO_BIG = CheckSpec(id="table_too_big", title="Таблица больше 7 строк или 5 колонок", severity="warn", category="density", description="Нативная таблица превышает 7 строк (с шапкой) или 5 колонок.")
TOO_MANY_SERIES = CheckSpec(id="too_many_series", title="Больше 5 серий на диаграмме", severity="warn", category="density", description="Нативная диаграмма содержит больше пяти рядов данных.")
FILL_RATIO = CheckSpec(id="fill_ratio", title="Слайд заполнен меньше чем на четверть или больше чем на 80%", severity="warn", category="density", description="Площадь объединения контентных блоков относительно безопасной области шаблона меньше 25% (меньше 20% при одном-двух блоках — сведение) или больше 80% — по тому, что действительно занято: у текста высота его строк, у диаграмм, таблиц и картинок весь блок (просторные карточки шаблона плотными не считаются).")


@check(TOO_MANY_BULLETS)
def too_many_bullets(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        for e in text_elements(s):
            n = sum(1 for p in e.paragraphs if (p.bullet or p.level > 0) and p.text.strip())
            if n > 6:
                out.append(ctx.new_issue(TOO_MANY_BULLETS, s.index, f"{ru_count(n, 'пункт', 'пункта', 'пунктов')} в одном списке", bboxes=[e.bbox_frac], element_ids=[e.id], autofix=fix("condense_text", "сократить список до 6 пунктов", outline_id=s.outline_id, element_id=e.id)))
    return out


@check(BULLET_TOO_LONG)
def bullet_too_long(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        for e in text_elements(s):
            long = [p.text for p in e.paragraphs if (p.bullet or p.level > 0) and len(p.text.split()) > 15]
            if long:
                out.append(ctx.new_issue(BULLET_TOO_LONG, s.index, f"{ru_count(len(long), 'пункт длиннее', 'пункта длиннее', 'пунктов длиннее')} 15 слов: «{long[0][:50]}…»", bboxes=[e.bbox_frac], element_ids=[e.id], autofix=fix("condense_text", "сократить пункты до 15 слов", outline_id=s.outline_id, element_id=e.id)))
    return out


@check(TABLE_TOO_BIG)
def table_too_big(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        for e in s.elements:
            if e.type == "table" and e.table:
                rows = len(e.table.rows)
                cols = max((len(r) for r in e.table.rows), default=0)
                if rows > 7 or cols > 5:
                    out.append(ctx.new_issue(TABLE_TOO_BIG, s.index, f"таблица {rows}×{cols}", bboxes=[e.bbox_frac], element_ids=[e.id]))
    return out


@check(TOO_MANY_SERIES)
def too_many_series(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        for e in s.elements:
            if e.type == "chart" and e.chart and len(e.chart.series) > 5:
                out.append(ctx.new_issue(TOO_MANY_SERIES, s.index, f"{ru_count(len(e.chart.series), 'серия', 'серии', 'серий')} данных на одной диаграмме", bboxes=[e.bbox_frac], element_ids=[e.id]))
    return out


def _ink(e) -> Bbox:
    """What a block really covers: a text box its lines (at the top of the box), anything else the whole box."""
    if e.type != "text" or not e.has_text:
        return e.bbox
    need, _ = text_height_needed_pt(e)
    h = min(e.bbox.h, int(need * EMU_PER_PT) + e.insets_emu[1] + e.insets_emu[3])
    return Bbox(x=e.bbox.x, y=e.bbox.y, w=e.bbox.w, h=max(h, 1))


@check(FILL_RATIO)
def fill_ratio(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    W, H = ctx.ir.slide_w, ctx.ir.slide_h
    safe = ctx.manifest.tokens.spacing.safe_area.to_emu(W, H)
    gx, gy = 96, 54

    def covered(boxes: list[Bbox]) -> float:
        # union area via coarse raster (fast, robust to overlaps)
        cells = set()
        for b in boxes:
            x0 = max(0, int((b.x - safe.x) / safe.w * gx))
            x1 = min(gx, int((b.x2 - safe.x) / safe.w * gx) + 1)
            y0 = max(0, int((b.y - safe.y) / safe.h * gy))
            y1 = min(gy, int((b.y2 - safe.y) / safe.h * gy) + 1)
            for xi in range(x0, x1):
                for yi in range(y0, y1):
                    cells.add((xi, yi))
        return len(cells) / (gx * gy)

    for s in ctx.ir.slides:
        els = content_elements(s, ctx.ir, ctx.manifest)
        if not els:
            continue
        ratio = covered([e.bbox for e in els])
        if ratio > 0.8:
            # too dense is about ink: roomy cards of the template's own grid with a line each are not a wall of text
            ratio = max(covered([_ink(e) for e in els]), 0.25)
        kind_hint = "title" if s.index == 1 else None
        if ratio < 0.2 and s.index not in (1, len(ctx.ir.slides)) and len(els) <= 2:
            out.append(ctx.new_issue(FILL_RATIO, s.index, f"слайд заполнен на {int(ratio * 100)}%", details={"ratio": round(ratio, 2)}, severity="info"))
        elif ratio < 0.25 and s.index not in (1, len(ctx.ir.slides)):
            out.append(ctx.new_issue(FILL_RATIO, s.index, f"слайд заполнен только на {int(ratio * 100)}%", details={"ratio": round(ratio, 2)}))
        elif ratio > 0.8:
            out.append(ctx.new_issue(FILL_RATIO, s.index, f"слайд заполнен на {int(ratio * 100)}%", details={"ratio": round(ratio, 2)}))
    return out
