"""Density checks: bullets, words, tables, series, fill ratio."""

from __future__ import annotations

from typing import Optional

from verstka.audit.checks.common import content_elements, fix, ru_count, text_elements, text_height_needed_pt, title_element
from verstka.audit.registry import AuditContext, check
from verstka.rendering.fonts import text_width_pt, wrap_lines
from verstka.schemas.audit import CheckSpec, Issue
from verstka.schemas.common import EMU_PER_PT, Bbox

TOO_MANY_BULLETS = CheckSpec(id="too_many_bullets", title="Больше 6 пунктов в одном списке", severity="warn", category="density", description="В одном текстовом блоке больше шести пунктов списка.")
BULLET_TOO_LONG = CheckSpec(id="bullet_too_long", title="Пункт списка длиннее 15 слов", severity="warn", category="density", description="Пункт списка (абзац с маркером) содержит больше 15 слов.")
TABLE_TOO_BIG = CheckSpec(id="table_too_big", title="Таблица больше 7 строк или 5 колонок", severity="warn", category="density", description="Нативная таблица превышает 7 строк (с шапкой) или 5 колонок.")
TOO_MANY_SERIES = CheckSpec(id="too_many_series", title="Больше 5 серий на диаграмме", severity="warn", category="density", description="Нативная диаграмма содержит больше пяти рядов данных.")
FILL_RATIO = CheckSpec(id="fill_ratio", title="Слайд заполнен меньше чем на четверть или больше чем на 80%", severity="warn", category="density", description="Площадь объединения контентных блоков относительно безопасной области шаблона меньше 25% (меньше 20% при одном-двух блоках — сведение) или больше 80% — по тому, что действительно занято: у текста высота его строк, у диаграмм, таблиц и картинок весь блок (просторные карточки шаблона плотными не считаются). Картинка во весь слайд (фон шаблона) контентом не считается. Слайд, где кроме заголовка только один-два текстовых блока (без диаграммы, таблицы и картинки, которую просил план; картинки-оформление шаблона не в счёт) и их строки занимают меньше 15% безопасной области, — почти пустой: предупреждение, даже если рисунок шаблона заполняет остальное (кроме обложки, разделов, цитат, финального слайда и слайда с одним крупным числом).")


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
                    if _asked_table(ctx, s):
                        # the person dictated this table row by row («Сделай сравнительную таблицу «Сейчас / Цель»: …»):
                        # its size is theirs — noted, not held against the deck
                        out.append(ctx.new_issue(TABLE_TOO_BIG, s.index, f"таблица {rows}×{cols} — такой её задали в тексте", severity="info", bboxes=[e.bbox_frac], element_ids=[e.id]))
                    else:
                        out.append(ctx.new_issue(TABLE_TOO_BIG, s.index, f"таблица {rows}×{cols}", bboxes=[e.bbox_frac], element_ids=[e.id]))
    return out


def _asked_table(ctx: AuditContext, s) -> bool:
    """The slide is one the brief describes («Слайд 9. …», spec_ref) and the brief asks for a table on it."""
    import re

    if not ctx.brief_text or ctx.outline is None or not s.outline_id:
        return False
    o = next((x for x in ctx.outline.slides if x.id == s.outline_id), None)
    if o is None or not getattr(o, "spec_ref", None):
        return False
    m = re.search(rf"(?:^|\n)\s*(?:слайд|slide)\s*{o.spec_ref}\b(.*?)(?=\n\s*(?:слайд|slide)\s*\d+\b|\Z)", ctx.brief_text, re.I | re.S)
    return bool(m and re.search(r"таблиц", m.group(1), re.I))


@check(TOO_MANY_SERIES)
def too_many_series(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        for e in s.elements:
            if e.type == "chart" and e.chart and len(e.chart.series) > 5:
                out.append(ctx.new_issue(TOO_MANY_SERIES, s.index, f"{ru_count(len(e.chart.series), 'серия', 'серии', 'серий')} данных на одной диаграмме", bboxes=[e.bbox_frac], element_ids=[e.id]))
    return out


def _ink(e) -> Bbox:
    """What a block really covers: a text box the band its lines fill (at its anchor: a figure set on the bottom of a
    tall box covers the bottom) and, without a fill or an outline of its own, no wider than its longest line — a
    short label in a wide column leaves the rest of the column empty; anything else the whole box."""
    if e.type != "text" or not e.has_text:
        return e.bbox
    need, _ = text_height_needed_pt(e)
    h = max(min(e.bbox.h, int(need * EMU_PER_PT) + e.insets_emu[1] + e.insets_emu[3]), 1)
    anchor = e.anchor or "t"
    y = e.bbox.y if anchor == "t" else (e.bbox.y2 - h if anchor == "b" else e.bbox.y + (e.bbox.h - h) // 2)
    x, w = e.bbox.x, e.bbox.w
    if not (e.fill_hex or e.line_hex) and e.wrap:
        usable = max((e.bbox.w - e.insets_emu[0] - e.insets_emu[2]) / EMU_PER_PT, 1.0)
        widest = 0.0
        for p in e.paragraphs:
            if not p.text.strip():
                continue
            size = next((r.size_pt for r in p.runs if r.size_pt), None) or e.dominant_size or 14.0
            font = next((r.font for r in p.runs if r.font), None)
            bold = any(r.bold for r in p.runs)
            indent = size * 1.1 if p.bullet else 0.0
            lines = wrap_lines(p.text.upper() if getattr(e, "caps", False) else p.text, font, size, bold, max(usable - indent, 1.0))
            widest = max(widest, indent + max((text_width_pt(t, font, size, bold) for t in lines), default=0.0))
        w = min(e.bbox.w, int(widest * EMU_PER_PT) + e.insets_emu[0] + e.insets_emu[2])
        align = next((p.align for p in e.paragraphs if p.text.strip() and p.align), None) or "l"
        if align in ("r",):
            x = e.bbox.x2 - w
        elif align in ("ctr", "c"):
            x = e.bbox.x + (e.bbox.w - w) // 2
    return Bbox(x=x, y=y, w=max(w, 1), h=h)


def _bleeds(e) -> bool:
    """The element covers ≥ 85 % of the slide."""
    f = e.bbox_frac
    return max(0.0, min(f.x2, 1.0) - max(f.x, 0.0)) * max(0.0, min(f.y2, 1.0) - max(f.y, 0.0)) >= 0.85


SPARSE_TEXT = 0.15  # a text-only slide whose lines cover less of the safe area than this is nearly empty
SPARSE_EXEMPT = ("title", "section", "thanks", "quote", "big_number", "image_text", "mockup")


def _sparse_text(ctx: AuditContext, s, els: list, covered) -> Optional[float]:
    """The share of the safe area the lines of a text-only slide cover when it is under SPARSE_TEXT (one or two short
    blocks under the heading — the writer's «one sentence» slide), else None. Pictures the plan did not ask for are the
    template's decoration and do not fill the slide; a chart, a table or a planned picture make it a different slide."""
    from verstka.audit.checks.template import is_figure

    osl = None
    if ctx.outline is not None and s.outline_id:
        osl = next((o for o in ctx.outline.slides if o.id == s.outline_id), None)
    kind = (osl.kind.value if hasattr(osl.kind, "value") else str(osl.kind)) if osl is not None else None
    if kind in SPARSE_EXEMPT or (kind is None and s.index in (1, len(ctx.ir.slides))):
        return None  # the last slide of a plan is checked by its kind: a content slide there is no closing slide
    planned_pic = osl is None or bool(osl.content.image_hint)
    title = title_element(s)
    body = [e for e in els if e is not title and e.type == "text" and e.has_text]
    if not body or len(body) > 2 or any(e.type in ("chart", "table") or (e.type == "picture" and planned_pic) for e in els):
        return None
    if any(is_figure(e.text) for e in body):
        return None  # a figure with its label: a hero number, set large on purpose
    ink = covered([_ink(e) for e in body])
    return ink if ink < SPARSE_TEXT else None


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
        # a full-bleed picture is the slide's ground (a gradient or photo background), not a block of content
        els = [e for e in content_elements(s, ctx.ir, ctx.manifest) if not (e.type == "picture" and _bleeds(e))]
        if not els:
            continue
        if s.index != 1:
            sparse = _sparse_text(ctx, s, els, covered)
            if sparse is not None:
                out.append(ctx.new_issue(FILL_RATIO, s.index, f"на слайде только короткий текст: его строки занимают {int(round(sparse * 100))}% области", details={"ratio": round(sparse, 2), "text_only": True}))
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
