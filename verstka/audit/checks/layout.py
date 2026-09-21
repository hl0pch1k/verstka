"""Layout checks: bounds, overlaps, overflow, margins, stretched images."""

from __future__ import annotations

from verstka.audit.checks.common import CONTENT_TYPES, content_elements, contains, fix, is_chrome_like, text_height_needed_pt, title_element, usable_height_pt
from verstka.audit.registry import AuditContext, check
from verstka.schemas.audit import CheckSpec, Issue

OUT_OF_BOUNDS = CheckSpec(id="out_of_bounds", title="Элемент вышел за границы слайда", severity="error", category="layout", description="Текст, таблица или диаграмма выходит за край слайда более чем на 1%; картинка — более чем на 25% своей площади.")
OVERLAP = CheckSpec(id="overlap", title="Два блока наложились друг на друга", severity="error", category="layout", description="Два текстовых блока пересекаются более чем на 30% меньшего из них (вложенность в карточку не считается).")
TEXT_OVERFLOW = CheckSpec(id="text_overflow", title="Текст не поместился в свою рамку", severity="error", category="layout", description="Оценка высоты текста по метрикам шрифта превышает высоту рамки более чем на 8% (сильное переполнение — ошибка, лёгкое — предупреждение).")
TEXT_CLIPPED = CheckSpec(id="text_clipped", title="Текст обрезан краем слайда", severity="error", category="layout", description="Рамка с текстом частично за пределами слайда.")
MARGIN_VIOLATION = CheckSpec(id="margin_violation", title="Контент заходит в поля у краёв", severity="warn", category="layout", description="Текстовый блок начинается за пределами безопасной области шаблона (допуск 3% ширины).")
GRID_ALIGNMENT = CheckSpec(id="grid_alignment", title="Блоки не выровнены по направляющим макета", severity="info", category="layout", description="Левый край текстового блока не совпадает ни с одной колонкой шаблона (допуск 1.5% ширины).")
IMAGE_STRETCHED = CheckSpec(id="image_stretched", title="Картинка растянута, пропорции нарушены", severity="warn", category="layout", description="Пропорции рамки картинки отличаются от пропорций исходного изображения (с учётом кадрирования) более чем на 12%.")


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
        for e in s.texts:
            f = e.bbox_frac
            if (f.x2 > 1.005 or f.y2 > 1.005 or f.x < -0.005 or f.y < -0.005) and f.x < 1.0 and f.y < 1.0:
                out.append(ctx.new_issue(TEXT_CLIPPED, s.index, f"текст «{e.text[:40]}» обрезан краем слайда", bboxes=[f], element_ids=[e.id], autofix=fix("rematch", "перевыбрать макет", outline_id=s.outline_id)))
    return out


@check(OVERLAP)
def overlap(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    for s in ctx.ir.slides:
        texts = [e for e in s.texts if not is_chrome_like(e, ctx.ir)]
        seen: set[tuple[str, str]] = set()
        for i, a in enumerate(texts):
            for b in texts[i + 1 :]:
                if (a.id, b.id) in seen:
                    continue
                inter = a.bbox.intersection(b.bbox)
                if inter <= 0:
                    continue
                smaller = min(a.bbox.area, b.bbox.area)
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


@check(TEXT_OVERFLOW)
def text_overflow(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    spacing = ctx.manifest.tokens.typography.line_spacing or 1.2
    for s in ctx.ir.slides:
        for e in s.texts:
            if e.bbox.h <= 0:
                continue
            need, lines = text_height_needed_pt(e, spacing)
            have = usable_height_pt(e)
            if have <= 0:
                continue
            ratio = need / have
            if ratio > 1.08:
                grows = e.autofit == "sp"  # PowerPoint enlarges such a box downwards
                grown_bottom = e.bbox.y + (need + (e.insets_emu[1] + e.insets_emu[3]) / 12700.0) * 12700
                is_title = e.ph_type in ("title", "ctrTitle") or (e is title_element(s))
                severe = ratio > (2.5 if is_title else 1.5)  # title boxes are generous and rarely collide
                if grows:
                    severity = "error" if grown_bottom > ctx.ir.slide_h * 1.0 else "warn"
                    msg = f"текст «{e.text[:40]}» вырастит рамку в {ratio:.1f} раза ({lines} строк)"
                else:
                    severity = "error" if severe else "warn"
                    msg = f"текст «{e.text[:40]}» выше рамки в {ratio:.1f} раза ({lines} строк)"
                out.append(
                    ctx.new_issue(
                        TEXT_OVERFLOW,
                        s.index,
                        msg,
                        bboxes=[e.bbox_frac],
                        element_ids=[e.id],
                        severity=severity,
                        details={"ratio": round(ratio, 2), "lines": lines, "autofit": e.autofit},
                        autofix=fix("rematch" if (severe and not grows) else "shrink_text", "перевыбрать макет" if (severe and not grows) else "уменьшить кегль по шкале шаблона", outline_id=s.outline_id, element_id=e.id, ratio=round(ratio, 2)),
                    )
                )
    return out


@check(MARGIN_VIOLATION)
def margin_violation(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    safe = ctx.manifest.tokens.spacing.safe_area
    for s in ctx.ir.slides:
        for e in s.texts:
            if is_chrome_like(e, ctx.ir) or e.nested:
                continue
            f = e.bbox_frac
            if f.x < safe.x - 0.03 or f.x2 > safe.x2 + 0.03 or f.y2 > safe.y2 + 0.05:
                out.append(ctx.new_issue(MARGIN_VIOLATION, s.index, f"«{e.text[:40]}» заходит в поля шаблона", bboxes=[f], element_ids=[e.id], autofix=fix("move_inside", "сдвинуть в безопасную область", element_id=e.id)))
    return out


@check(GRID_ALIGNMENT)
def grid_alignment(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    cols = ctx.manifest.tokens.spacing.columns
    if not cols:
        return out
    for s in ctx.ir.slides:
        misaligned = []
        for e in s.texts:
            if is_chrome_like(e, ctx.ir) or e.nested or e.bbox_frac.w < 0.2:
                continue
            if all(abs(e.bbox_frac.x - c) > 0.015 for c in cols):
                misaligned.append(e)
        if len(misaligned) >= 2:
            out.append(ctx.new_issue(GRID_ALIGNMENT, s.index, f"{len(misaligned)} блоков не выровнены по колонкам шаблона", bboxes=[e.bbox_frac for e in misaligned[:4]], element_ids=[e.id for e in misaligned]))
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
