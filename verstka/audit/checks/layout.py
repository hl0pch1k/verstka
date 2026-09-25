"""Layout checks: bounds, overlaps, overflow, margins, stretched images, table cells."""

from __future__ import annotations

import re

from verstka.audit.checks.template import is_figure
from verstka.audit.checks.common import CONTENT_TYPES, at_template_position, contains, fix, is_chrome_like, ru_count, ru_times, text_elements, text_height_needed_pt, title_element, usable_height_pt
from verstka.audit.registry import AuditContext, check
from verstka.rendering.fonts import text_width_pt
from verstka.schemas.audit import CheckSpec, Issue
from verstka.schemas.common import EMU_PER_PT, Bbox

OUT_OF_BOUNDS = CheckSpec(id="out_of_bounds", title="Элемент вышел за границы слайда", severity="error", category="layout", description="Текст, таблица или диаграмма выходит за край слайда более чем на 1%; картинка — более чем на 25% своей площади.")
OVERLAP = CheckSpec(id="overlap", title="Два блока наложились друг на друга", severity="error", category="layout", description="Два текстовых блока пересекаются более чем на 30% меньшего из них (вложенность в карточку не считается). У рамки без заливки и обводки считается полоса, которую занимают её строки (по привязке к верху, центру или низу): пустая часть рамки ничего не закрывает.")
TEXT_OVERFLOW = CheckSpec(id="text_overflow", title="Текст не поместился в свою рамку", severity="error", category="layout", description="Оценка высоты текста по метрикам шрифта превышает высоту рамки более чем на 8% (сильное переполнение — ошибка, лёгкое — предупреждение).")
TEXT_CLIPPED = CheckSpec(id="text_clipped", title="Текст обрезан краем слайда", severity="error", category="layout", description="Рамка с текстом частично за пределами слайда.")
MARGIN_VIOLATION = CheckSpec(id="margin_violation", title="Контент заходит в поля у краёв", severity="warn", category="layout", description="Текстовый блок начинается за пределами безопасной области шаблона (допуск 3% ширины).")
GRID_ALIGNMENT = CheckSpec(id="grid_alignment", title="Блоки не выровнены по направляющим макета", severity="info", category="layout", description="Левый край текстового блока не совпадает ни с одной колонкой шаблона (допуск 1.5% ширины).")
IMAGE_STRETCHED = CheckSpec(id="image_stretched", title="Картинка растянута, пропорции нарушены", severity="warn", category="layout", description="Пропорции рамки картинки отличаются от пропорций исходного изображения (с учётом кадрирования) более чем на 12%.")
TEXT_OUTSIDE_CARD = CheckSpec(id="text_outside_card", title="Текст выходит за свою карточку", severity="error", category="layout", description="Строки текстового блока, который начинается внутри карточки (залитой или обведённой фигуры), заходят за её нижний или правый край более чем на 1,5% размера слайда (больше 3% — ошибка): текст висит под карточкой и наезжает на то, что ниже.")
TABLE_CELL_WRAP = CheckSpec(id="table_cell_wrap", title="Слово в ячейке таблицы переносится по буквам", severity="warn", category="layout", description="Самое длинное слово в ячейке нативной таблицы шире своей колонки (ширина из a:gridCol минус поля ячейки; без сетки — ширина рамки / число колонок минус 2×7.2 пт) при кегле и начертании самой ячейки — PowerPoint рвёт его посреди слова.")

WORD_BREAK = CheckSpec(id="word_break", title="Слово шире своей рамки и рвётся посередине", severity="warn", category="layout", description="Слово абзаца (по метрикам шрифта, при кегле и начертании своего фрагмента) шире рамки текста за вычетом полей и отступа маркера — рендерер разорвёт его посреди слова («Корректировк / а»). Допуск 3%: рендерер набирает текст чуть шире, чем его меряют; неразрывный пробел держит слова вместе, дефис без словосоединителя — место переноса. Рамки, которые сами уменьшают шрифт (normAutofit), и служебные элементы шаблона (номер слайда, дата, колонтитул) не проверяются.")

TABLE_CELL_INSET_PT = 7.2  # default a:tcPr marL/marR
WORD_ROOM = 0.97  # a word wider than this share of its line is broken by the renderer
_HARD_SPACE_RE = re.compile(r"[ \t\r\n]+")  # NBSP stays inside a word, as PowerPoint keeps it on one line


@check(OUT_OF_BOUNDS)
def out_of_bounds(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    W, H = ctx.ir.slide_w, ctx.ir.slide_h
    for s in ctx.ir.slides:
        for e in s.elements:
            if e.type not in CONTENT_TYPES or e.bbox.area <= 0:
                continue
            f = e.bbox_frac
            if e.type == "picture":
                inside_w = max(0.0, min(f.x2, 1.0) - max(f.x, 0.0))
                inside_h = max(0.0, min(f.y2, 1.0) - max(f.y, 0.0))
                if inside_w * inside_h < 0.75 * f.area:
                    out.append(ctx.new_issue(OUT_OF_BOUNDS, s.index, f"картинка «{e.name}» на {100 - int(100 * inside_w * inside_h / max(f.area, 1e-9))}% за краем слайда", bboxes=[f], element_ids=[e.id], severity="warn", autofix=fix("move_inside", "сдвинуть внутрь слайда", element_id=e.id)))
                continue
            if f.x < -0.01 or f.y < -0.01 or f.x2 > 1.01 or f.y2 > 1.01:
                out.append(ctx.new_issue(OUT_OF_BOUNDS, s.index, f"«{(e.text[:40] or e.name)}» выходит за край слайда", bboxes=[f], element_ids=[e.id], autofix=fix("move_inside", "сдвинуть внутрь слайда", element_id=e.id)))
    return out


@check(TEXT_CLIPPED)
def text_clipped(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        for e in text_elements(s):
            f = e.bbox_frac
            if (f.x2 > 1.005 or f.y2 > 1.005 or f.x < -0.005 or f.y < -0.005) and f.x < 1.0 and f.y < 1.0:
                out.append(ctx.new_issue(TEXT_CLIPPED, s.index, f"текст «{e.text[:40]}» обрезан краем слайда", bboxes=[f], element_ids=[e.id], autofix=fix("rematch", "перевыбрать макет", outline_id=s.outline_id)))
    return out


def _occupied(e, spacing: float) -> Bbox:
    """The band of a text box its lines fill: a box without fill or outline shows only its text, so its empty part
    (the ascender room over a figure set on the box's bottom) overlaps nothing."""
    if e.fill_hex or e.line_hex:
        return e.bbox
    need, lines = text_height_needed_pt(e, spacing)
    if lines == 1 and is_figure(e.text.strip()):
        # a figure shows its digits: the ascender room of a 160 pt line over them is empty
        from verstka.rendering.fonts import figure_metrics_em

        size = max((r.size_pt or 0.0) for p in e.paragraphs for r in p.runs) or need
        descent, digit_h = figure_metrics_em(any(r.bold for p in e.paragraphs for r in p.runs))
        need = min(need, (descent + digit_h) * size * 1.05)
    h = int(need * EMU_PER_PT) + e.insets_emu[1] + e.insets_emu[3]
    if h >= e.bbox.h:
        return e.bbox
    anchor = e.anchor or "t"
    y = e.bbox.y if anchor == "t" else (e.bbox.y2 - h if anchor == "b" else e.bbox.y + (e.bbox.h - h) // 2)
    return Bbox(x=e.bbox.x, y=y, w=e.bbox.w, h=h)


@check(OVERLAP)
def overlap(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    spacing = ctx.manifest.tokens.typography.line_height
    for s in ctx.ir.slides:
        texts = [e for e in text_elements(s) if not is_chrome_like(e, ctx.ir, ctx.manifest)]
        seen: set[tuple[str, str]] = set()
        for i, a in enumerate(texts):
            for b in texts[i + 1 :]:
                if (a.id, b.id) in seen:
                    continue
                oa, ob = _occupied(a, spacing), _occupied(b, spacing)
                inter = oa.intersection(ob)
                if inter <= 0:
                    continue
                smaller = min(oa.area, ob.area)
                if smaller <= 0:
                    continue
                # a filled card holding a text box is intended nesting
                if (a.fill_hex and contains(a.bbox, b.bbox)) or (b.fill_hex and contains(b.bbox, a.bbox)):
                    continue
                ratio = inter / smaller
                if ratio > 0.3:
                    seen.add((a.id, b.id))
                    out.append(
                        ctx.new_issue(
                            OVERLAP,
                            s.index,
                            f"«{a.text[:30]}» и «{b.text[:30]}» пересекаются на {int(ratio * 100)}%",
                            bboxes=[a.bbox_frac, b.bbox_frac],
                            element_ids=[a.id, b.id],
                            severity="error" if ratio > 0.5 else "warn",
                            details={"ratio": round(ratio, 2)},
                            autofix=fix("rematch", "перевыбрать макет слайда", outline_id=s.outline_id),
                        )
                    )
    return out


@check(TEXT_OUTSIDE_CARD)
def text_outside_card(ctx: AuditContext) -> list[Issue]:
    """A text that starts inside a card (the smallest filled or outlined shape holding its first line) and whose lines
    run past the card's bottom or right edge: the column of a two-column slide whose list hangs below its card."""
    out: list[Issue] = []
    W, H = ctx.ir.slide_w, ctx.ir.slide_h
    spacing = ctx.manifest.tokens.typography.line_height
    for s in ctx.ir.slides:
        cards = [o for o in s.elements if o.type in ("shape", "text") and (o.fill_hex or o.line_hex) and o.bbox.area > 0 and not o.has_text]
        for e in text_elements(s):
            if is_chrome_like(e, ctx.ir, ctx.manifest) or e.fill_hex or e.line_hex:
                continue
            occ = _occupied(e, spacing)
            x0, y0 = occ.x + min(occ.w // 20, int(0.01 * W)), occ.y + min(occ.h // 20, int(0.01 * H))
            hosts = [c for c in cards if c.bbox.x <= x0 <= c.bbox.x2 and c.bbox.y <= y0 <= c.bbox.y2 and c.bbox.area > occ.area * 0.3]
            if not hosts:
                continue
            host = min(hosts, key=lambda c: c.bbox.area)
            below = occ.y2 - host.bbox.y2
            right = occ.x2 - host.bbox.x2
            over = max(below / max(H, 1), right / max(W, 1))
            # or its lines run into another card under or beside it (a card that grew into the conclusion strip)
            for c in cards:
                if c is host or c.bbox.area <= 0 or contains(c.bbox, host.bbox) or contains(host.bbox, c.bbox):
                    continue
                inter_h = min(occ.y2, c.bbox.y2) - max(occ.y, c.bbox.y)
                inter_w = min(occ.x2, c.bbox.x2) - max(occ.x, c.bbox.x)
                if inter_h > 0 and inter_w > 0.3 * occ.w:
                    over = max(over, inter_h / max(H, 1))
            if over <= 0.015:
                continue
            out.append(
                ctx.new_issue(
                    TEXT_OUTSIDE_CARD,
                    s.index,
                    f"текст «{e.text[:40]}» выходит за свою карточку на {int(round(over * 100))}% слайда",
                    bboxes=[e.bbox_frac, host.bbox_frac],
                    element_ids=[e.id, host.id],
                    severity="error" if over > 0.03 else "warn",
                    details={"over": round(over, 3)},
                    autofix=fix("rematch", "перевыбрать макет слайда", outline_id=s.outline_id),
                )
            )
    return out


@check(TEXT_OVERFLOW)
def text_overflow(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    spacing = ctx.manifest.tokens.typography.line_height
    for s in ctx.ir.slides:
        title = title_element(s)
        for e in text_elements(s):
            if e.bbox.h <= 0:
                continue
            need, lines = text_height_needed_pt(e, spacing)
            have = usable_height_pt(e)
            if have <= 0:
                continue
            ratio = need / have
            if ratio > 1.08:
                grows = e.autofit == "sp"  # PowerPoint enlarges such a box downwards
                shrinks = e.autofit == "norm" and ratio <= 2.5  # PowerPoint shrinks the text itself; nothing to fix
                grown_bottom = e.bbox.y + (need + (e.insets_emu[1] + e.insets_emu[3]) / 12700.0) * 12700
                is_title = e.ph_type in ("title", "ctrTitle") or (e is title)
                severe = ratio > (2.5 if is_title else 1.5)  # title boxes are generous and rarely collide
                if grows:
                    severity = "error" if grown_bottom > ctx.ir.slide_h * 1.0 else "warn"
                    msg = f"текст «{e.text[:40]}» вырастит рамку {ru_times(ratio)} ({ru_count(lines, 'строка', 'строки', 'строк')})"
                elif shrinks:
                    severity = "info"
                    msg = f"текст «{e.text[:40]}» выше рамки {ru_times(ratio)} ({ru_count(lines, 'строка', 'строки', 'строк')}), рамка сама уменьшит шрифт"
                else:
                    severity = "error" if severe else "warn"
                    msg = f"текст «{e.text[:40]}» выше рамки {ru_times(ratio)} ({ru_count(lines, 'строка', 'строки', 'строк')})"
                rematch = severe and not grows and not shrinks
                out.append(
                    ctx.new_issue(
                        TEXT_OVERFLOW,
                        s.index,
                        msg,
                        bboxes=[e.bbox_frac],
                        element_ids=[e.id],
                        severity=severity,
                        details={"ratio": round(ratio, 2), "lines": lines, "autofit": e.autofit},
                        autofix=None if shrinks else fix("rematch" if rematch else "shrink_text", "перевыбрать макет" if rematch else "уменьшить шрифт по шкале шаблона", outline_id=s.outline_id, element_id=e.id, ratio=round(ratio, 2)),
                    )
                )
    return out


@check(MARGIN_VIOLATION)
def margin_violation(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    safe = ctx.manifest.tokens.spacing.safe_area
    for s in ctx.ir.slides:
        for e in text_elements(s):
            if is_chrome_like(e, ctx.ir, ctx.manifest) or e.nested or at_template_position(e, ctx.manifest):
                continue
            f = e.bbox_frac
            if f.x < safe.x - 0.03 or f.x2 > safe.x2 + 0.03 or f.y2 > safe.y2 + 0.05:
                out.append(ctx.new_issue(MARGIN_VIOLATION, s.index, f"«{e.text[:40]}» заходит в поля шаблона", bboxes=[f], element_ids=[e.id], autofix=fix("move_inside", "сдвинуть в безопасную область", element_id=e.id, safe=True)))
    return out


@check(GRID_ALIGNMENT)
def grid_alignment(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    cols = ctx.manifest.tokens.spacing.columns
    if not cols:
        return out
    for s in ctx.ir.slides:
        misaligned = []
        for e in text_elements(s):
            if is_chrome_like(e, ctx.ir, ctx.manifest) or e.nested or e.bbox_frac.w < 0.2:
                continue
            if all(abs(e.bbox_frac.x - c) > 0.015 for c in cols):
                misaligned.append(e)
        if len(misaligned) >= 2:
            out.append(ctx.new_issue(GRID_ALIGNMENT, s.index, f"{ru_count(len(misaligned), 'блок не выровнен', 'блока не выровнены', 'блоков не выровнены')} по колонкам шаблона", bboxes=[e.bbox_frac for e in misaligned[:4]], element_ids=[e.id for e in misaligned]))
    return out


@check(IMAGE_STRETCHED)
def image_stretched(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        for e in s.elements:
            if e.type != "picture" or not e.image_size or e.bbox.h <= 0:
                continue
            iw, ih = e.image_size
            if iw <= 0 or ih <= 0:
                continue
            l, t, r, b = e.crop or (0.0, 0.0, 0.0, 0.0)
            cw = iw * max(1 - l - r, 0.01)
            ch = ih * max(1 - t - b, 0.01)
            img_ar = cw / ch
            box_ar = e.bbox.w / e.bbox.h
            dev = abs(box_ar / img_ar - 1)
            if dev > 0.12:
                out.append(ctx.new_issue(IMAGE_STRETCHED, s.index, f"картинка «{e.name}» искажена на {int(dev * 100)}%", bboxes=[e.bbox_frac], element_ids=[e.id], details={"deviation": round(dev, 2)}))
    return out


@check(TABLE_CELL_WRAP)
def table_cell_wrap(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    family = ctx.manifest.tokens.typography.primary_family
    size = ctx.manifest.components.table_style.font_size_pt or 12.0
    for s in ctx.ir.slides:
        for e in s.elements:
            if e.type != "table" or not e.table or not e.table.rows or e.bbox.w <= 0:
                continue
            n_cols = max((len(r) for r in e.table.rows), default=0)
            if n_cols == 0:
                continue
            grid = e.table.col_widths_emu if len(e.table.col_widths_emu) == n_cols and all(w > 0 for w in e.table.col_widths_emu) else None
            uniform_pt = e.bbox.w / EMU_PER_PT / n_cols - 2 * TABLE_CELL_INSET_PT  # no grid: uniform columns
            worst: tuple[float, str, int, float, float] | None = None
            for r_i, row in enumerate(e.table.rows):
                for c_i, cell in enumerate(row):
                    info = e.table.cells[r_i][c_i] if r_i < len(e.table.cells) and c_i < len(e.table.cells[r_i]) else None
                    if grid and c_i < len(grid):  # the real column, less this cell's own margins, at its own size
                        col_pt = grid[c_i] / EMU_PER_PT - ((info.mar_l_pt + info.mar_r_pt) if info else 2 * TABLE_CELL_INSET_PT)
                    else:
                        col_pt = uniform_pt
                    cell_size = (info.size_pt if info and info.size_pt else size)
                    cell_bold = info.bold if info and info.size_pt else (r_i == 0)
                    for word in _HARD_SPACE_RE.split(cell or ""):
                        if not word:
                            continue
                        w_pt = text_width_pt(word, family, cell_size, bold=cell_bold)
                        if w_pt > col_pt + 0.5 and (worst is None or w_pt - col_pt > worst[0]):
                            worst = (w_pt - col_pt, word, c_i, col_pt, cell_size)
            if worst is not None:
                over, word, c_i, col_pt, w_size = worst
                out.append(
                    ctx.new_issue(
                        TABLE_CELL_WRAP,
                        s.index,
                        f"слово «{word}» ({col_pt + over:.0f} пт) шире колонки {c_i + 1} таблицы ({col_pt:.0f} пт при {w_size:g} пт) и рвётся по буквам",
                        bboxes=[e.bbox_frac],
                        element_ids=[e.id],
                        details={"word": word, "column": c_i, "word_pt": round(col_pt + over, 1), "column_pt": round(col_pt, 1), "cols": n_cols},
                        autofix=fix("rematch", "перевыбрать макет с более широкой областью таблицы", outline_id=s.outline_id),
                    )
                )
    return out


_WORD_SPLIT_RE = re.compile(r"[ \t\r\n]+|(?<=-)(?!\u2060)")


@check(WORD_BREAK)
def word_break(ctx: AuditContext) -> list[Issue]:
    """A word wider than the line it stands on: a column too narrow for it (six steps in a row, a card of a long
    word) — the renderer breaks it in the middle."""
    out: list[Issue] = []
    for s in ctx.ir.slides:
        for e in text_elements(s):
            if not e.wrap or e.autofit == "norm" or e.rotation or e.bbox.w <= 0:
                continue
            if e.ph_type in ("sldNum", "dt", "ftr") or is_chrome_like(e, ctx.ir, ctx.manifest):
                continue  # the template's own page number, date and footer boxes: its chrome, not the deck's text
            usable = (e.bbox.w - e.insets_emu[0] - e.insets_emu[2]) / EMU_PER_PT
            if usable <= 0:
                continue
            worst: tuple[float, str, float] | None = None
            for p in e.paragraphs:
                size_p = next((r.size_pt for r in p.runs if r.size_pt), None) or e.dominant_size or 14.0
                line = usable - (size_p * 1.1 if p.bullet else 0.0)
                for r in p.runs:
                    size = r.size_pt or size_p
                    for word in _WORD_SPLIT_RE.split(r.text or ""):
                        if not word.strip():
                            continue
                        w_pt = text_width_pt(word, r.font, size, r.bold)
                        if w_pt > line * WORD_ROOM and (worst is None or w_pt - line > worst[0] - worst[2]):
                            worst = (w_pt, word, line)
            if worst is not None:
                w_pt, word, line = worst
                out.append(
                    ctx.new_issue(
                        WORD_BREAK,
                        s.index,
                        f"слово «{word.strip()}» ({w_pt:.0f} пт) не помещается в строку рамки ({line:.0f} пт) и рвётся посередине",
                        bboxes=[e.bbox_frac],
                        element_ids=[e.id],
                        details={"word": word.strip(), "word_pt": round(w_pt, 1), "line_pt": round(line, 1)},
                        autofix=fix("shrink_text", "уменьшить шрифт по шкале шаблона, чтобы слово встало в строку", outline_id=s.outline_id, element_id=e.id, ratio=round(w_pt / (line * WORD_ROOM), 2)),
                    )
                )
    return out
