"""Template compliance checks: fonts, sizes, colours, layouts, chrome, contrast."""

from __future__ import annotations

import re

from typing import Optional

from verstka.analysis.chrome import shape_signature
from verstka.audit.checks.common import composite_hex, enclosing_fill, fill_alpha, fix, is_chrome_like, ru_count, text_elements
from verstka.audit.registry import AuditContext, check
from verstka.schemas.audit import CheckSpec, Issue
from verstka.schemas.common import Color, contrast_ratio

FONT_NOT_IN_TEMPLATE = CheckSpec(id="font_not_in_template", title="Шрифт не из шаблона или гарнитур больше двух", severity="error", category="template", description="Гарнитура рана отсутствует среди шрифтов шаблона (используемых или встроенных), либо на слайде больше двух гарнитур.")
SIZE_NOT_IN_SCALE = CheckSpec(id="size_not_in_scale", title="Размер шрифта не из шкалы шаблона", severity="warn", category="template", description="Размер шрифта отличается более чем на 0,75 пт от всех размеров, встречающихся в шаблоне. Крупные числа (значение с единицей, от наибольшего кегля шаблона или вдвое крупнее основного текста) — отдельная ступень шкалы: они не проверяются.")
COLOR_NOT_IN_PALETTE = CheckSpec(id="color_not_in_palette", title="Цвет не из палитры шаблона", severity="warn", category="template", description="Цвет текста или заливки отстоит от ближайшего цвета палитры шаблона больше чем на ΔE 6.")
LAYOUT_NOT_FROM_TEMPLATE = CheckSpec(id="layout_not_from_template", title="Слайд собран не на макете из шаблона", severity="error", category="template", description="Слайд ссылается на макет, которого нет в пакете шаблона.")
CHROME_MOVED = CheckSpec(id="chrome_moved", title="Логотип или колонтитул сдвинуты с положенного места", severity="warn", category="template", description="Элемент хрома шаблона (логотип, колонтитул на слайдах) отсутствует или стоит в другом месте.")
TABLE_CONTRAST_LOW = CheckSpec(id="table_contrast_low", title="Контраст текста в таблице ниже нормы", severity="warn", category="template", description="Контраст по WCAG между текстом ячейки таблицы и её заливкой (или фоном слайда) ниже 4.5:1 для обычного текста и 3:1 для крупного (≥18 пт или ≥14 пт жирным) и для значков ✓ / —. Пара цветов шаблона (белый на фирменном синем) от 3:1 — только справка.")
CONTRAST_LOW = CheckSpec(id="contrast_low", title="Контраст текста к фону ниже 4.5:1", severity="warn", category="template", description="Контраст по WCAG между цветом текста и фоном (карточка с учётом прозрачности заливки или фон слайда) ниже 4.5:1 для обычного текста и 3:1 для крупного (≥18 пт или ≥14 пт жирным).")

CONTRAST_CANDIDATE_ROLES = ("text.primary", "text.secondary")


def _allowed_fonts(ctx: AuditContext) -> set[str]:
    fam = {f.family.lower() for f in ctx.manifest.tokens.typography.families if f.weight > 0}  # anything the template itself uses
    fam |= {f.lower() for f in ctx.manifest.embedded_fonts}
    fam |= {f.lower() for f in ctx.ir.embedded_fonts}
    return fam


@check(FONT_NOT_IN_TEMPLATE)
def font_not_in_template(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    allowed = _allowed_fonts(ctx)
    if not allowed:
        return out
    for s in ctx.ir.slides:
        used: dict[str, list[str]] = {}
        for e in text_elements(s):
            for p in e.paragraphs:
                for r in p.runs:
                    if r.font and r.text.strip():
                        used.setdefault(r.font, []).append(e.id)
        bad = {f: ids for f, ids in used.items() if f.lower() not in allowed and not f.startswith("+")}
        for f, ids in bad.items():
            out.append(ctx.new_issue(FONT_NOT_IN_TEMPLATE, s.index, f"шрифт «{f}» отсутствует в шаблоне", element_ids=sorted(set(ids)), bboxes=[s.by_id(i).bbox_frac for i in sorted(set(ids))[:3] if s.by_id(i)], autofix=fix("refont", "заменить на основной шрифт шаблона", element_ids=sorted(set(ids)))))
        if len(used) > 2:
            out.append(ctx.new_issue(FONT_NOT_IN_TEMPLATE, s.index, f"на слайде {ru_count(len(used), 'шрифт', 'шрифта', 'шрифтов')}: {', '.join(sorted(used))}", severity="warn"))
    return out


_FIGURE_RE = re.compile(r"^[\s+\-−–×x~≈«»]*\d[\d\s\u00a0\u202f.,]*(%|[a-zа-яё₽$€]{0,6}\.?(?:[\s\u00a0][₽$€])?)?(\s?[→\-–/]\s?[\d\s.,]+(%|[a-zа-яё₽]{0,6}\.?)?)?\s*$", re.I)


def is_figure(text: str) -> bool:
    """«6,5», «40%», «×4,8», «27 млн», «31% → 12%»: a value set as a figure, not running text."""
    t = text.strip()
    return 0 < len(t) <= 16 and bool(_FIGURE_RE.match(t))


@check(SIZE_NOT_IN_SCALE)
def size_not_in_scale(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    sizes = ctx.manifest.tokens.typography.sizes_used or [st.size_pt for st in ctx.manifest.tokens.typography.scale]
    if not sizes:
        return out
    # sizes the samples inherit from their layouts (a cover title set at 48 pt by the placeholder) are the template's own
    sizes = sorted(set(sizes) | {sl.style.size_pt for p in ctx.manifest.patterns for sl in p.slots if sl.style.size_pt})
    body = ctx.manifest.tokens.typography.size_for("body", 14.0)
    display_from = min(max(sizes), 2 * body)
    for s in ctx.ir.slides:
        bad: dict[float, list[str]] = {}
        for e in text_elements(s):
            for p in e.paragraphs:
                for r in p.runs:
                    if r.size_pt and r.size_pt >= display_from and is_figure(r.text):
                        continue  # the display step of the scale: figures may be set larger than any text
                    if r.size_pt and r.text.strip() and all(abs(r.size_pt - t) > 0.75 for t in sizes):
                        bad.setdefault(r.size_pt, []).append(e.id)
        for sz, ids in bad.items():
            out.append(ctx.new_issue(SIZE_NOT_IN_SCALE, s.index, f"размер шрифта {sz:g} пт не из шкалы шаблона", element_ids=sorted(set(ids)), severity="info" if any(abs(sz - t) <= 2.0 for t in sizes) else "warn", details={"size": sz}))
    return out


@check(COLOR_NOT_IN_PALETTE)
def color_not_in_palette(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    palette = [Color(hex=h) for h in ctx.manifest.tokens.palette()]
    if not palette:
        return out

    def nearest(hex_: str) -> float:
        c = Color(hex=hex_)
        return min(Color.delta_e(c, p) for p in palette)

    for s in ctx.ir.slides:
        seen: dict[str, list[str]] = {}
        for e in s.elements:
            if e.type == "chart":
                continue  # chart colours come from the palette by construction; sample charts are removed
            cands = []
            if e.fill_hex and e.type in ("shape", "text"):
                cands.append(e.fill_hex)
            for p in e.paragraphs:
                for r in p.runs:
                    if r.color_hex and r.text.strip():
                        cands.append(r.color_hex)
            for h in cands:
                try:
                    d = nearest(h)
                except ValueError:
                    continue
                if d > 6.0:
                    seen.setdefault(h, []).append(e.id)
        for h, ids in seen.items():
            out.append(ctx.new_issue(COLOR_NOT_IN_PALETTE, s.index, f"цвет #{h} не из палитры шаблона", element_ids=sorted(set(ids)), autofix=fix("recolor", "заменить ближайшим цветом палитры", hex=h, element_ids=sorted(set(ids)), scope="all")))
    return out


@check(LAYOUT_NOT_FROM_TEMPLATE)
def layout_not_from_template(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    known = set(ctx.ir.layout_parts)
    for s in ctx.ir.slides:
        if s.layout_part and s.layout_part not in known:
            out.append(ctx.new_issue(LAYOUT_NOT_FROM_TEMPLATE, s.index, f"макет {s.layout_part} отсутствует в шаблоне"))
    return out


def _chrome_name(c) -> str:
    """What a person calls a repeated template element: a logo, the slide number, a caption."""
    text = (c.text or "").strip()
    if c.kind == "pic":
        return "логотип или картинка шаблона"
    if text.isdigit():
        return "номер слайда"
    if text:
        return f"надпись шаблона «{text[:30]}»"
    return "элемент оформления шаблона"


@check(CHROME_MOVED)
def chrome_moved(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    slide_chrome = [c for c in ctx.manifest.tokens.chrome if c.source == "slide" and c.share >= 0.6]
    if not slide_chrome:
        return out
    for s in ctx.ir.slides:
        for c in slide_chrome:
            present = False
            for e in s.elements:
                if (c.kind == "pic") != (e.type == "picture"):
                    continue
                if e.bbox_frac.close_to(c.bbox, 0.02) and (not c.text or c.text.strip()[:20] == e.text.strip()[:20] or c.text.strip().isdigit()):
                    present = True
                    break
            if not present:
                out.append(ctx.new_issue(CHROME_MOVED, s.index, f"{_chrome_name(c)} отсутствует или стоит не на своём месте", bboxes=[c.bbox], severity="info"))
    return out


def _contrast_replacement(tokens, bg: str, need: float) -> Optional[str]:
    """First template text colour (then white, black) that reaches the required ratio against bg; None if nothing does."""
    cands: list[str] = []
    for role in CONTRAST_CANDIDATE_ROLES:
        hx = tokens.color_for(role)
        if hx:
            cands.append(hx.upper())
    cands.extend(("FFFFFF", "000000"))
    for c in dict.fromkeys(cands):
        try:
            if contrast_ratio(c, bg) >= need:
                return c
        except ValueError:
            continue
    return None


@check(CONTRAST_LOW)
def contrast_low(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    tokens = ctx.manifest.tokens
    for s in ctx.ir.slides:
        bg_slide = s.background_hex or tokens.color_for("background.dark" if s.family.value == "dark" else "background.light") or ("000000" if s.family.value == "dark" else "FFFFFF")
        for e in text_elements(s):
            if is_chrome_like(e, ctx.ir, ctx.manifest):
                continue
            color = e.dominant_color
            if not color:
                continue
            enclosing = enclosing_fill(s, e, bg_slide)
            under = enclosing or bg_slide
            # a picture or gradient ground: its colour under the text is unknown here — report, never recolour
            uncertain = enclosing is None and not s.background_hex
            try:
                bg = composite_hex(e.fill_hex, fill_alpha(e), under) if e.fill_hex else under
                cr = contrast_ratio(color, bg)
            except ValueError:
                continue
            size = e.dominant_size or 14.0
            bold = any(r.bold for p in e.paragraphs for r in p.runs if r.text.strip())
            need = 3.0 if size >= 18 or (bold and size >= 14) else 4.5  # WCAG: large text is 18 pt, or 14 pt bold
            if cr < need:
                accent_text = any(t.hex == color and any(r.startswith("accent.") for r in t.roles) for t in tokens.colors)
                severity = "error" if cr < 2.5 else ("info" if (accent_text and cr >= 3.0) else "warn")  # brand accent on dark is the template's own choice
                # the heading keeps the template's own colour (white on a pink pill is the design, not a slip)
                is_heading = e.ph_type in ("title", "ctrTitle")
                if is_heading and severity != "error":
                    severity = "info"
                to = None if uncertain or is_heading else _contrast_replacement(tokens, bg, need)
                autofix = fix("recolor", f"заменить цвет текста на #{to}", element_ids=[e.id], to=to, scope="text") if to else None
                if uncertain:
                    severity = "info"
                out.append(ctx.new_issue(CONTRAST_LOW, s.index, f"контраст {cr:.1f}:1 у «{e.text[:30]}» (#{color} на #{bg})", bboxes=[e.bbox_frac], element_ids=[e.id], severity=severity, details={"contrast": round(cr, 2), "background": bg}, autofix=autofix))
    return out


_TABLE_MARKS = {"✓", "✔", "✗", "✕", "×", "—", "–", "-", "−", "+"}


@check(TABLE_CONTRAST_LOW)
def table_contrast_low(ctx: AuditContext) -> list[Issue]:
    """Table text against its cell fill, or the slide ground under an unfilled cell. One issue per table (the worst
    cell). A pairing of two template colours (white on the brand blue) between 3:1 and 4.5:1 is the template's own
    choice: reported as info."""
    out: list[Issue] = []
    tokens = ctx.manifest.tokens
    palette = {t.hex.upper() for t in tokens.colors} | {"FFFFFF", "000000"}
    for s in ctx.ir.slides:
        ground = s.background_hex
        for e in s.elements:
            if e.type != "table" or not e.table or not e.table.cells:
                continue
            worst = None
            for r_i, row in enumerate(e.table.cells):
                for c_i, cell in enumerate(row):
                    text = e.table.rows[r_i][c_i] if r_i < len(e.table.rows) and c_i < len(e.table.rows[r_i]) else ""
                    bg = cell.fill_hex or ground
                    if not text.strip() or not cell.color_hex or not bg:
                        continue
                    try:
                        cr = contrast_ratio(cell.color_hex, bg)
                    except ValueError:
                        continue
                    size = cell.size_pt or 14.0
                    mark = text.strip() in _TABLE_MARKS  # ✓ / — are marks, not text: the icon gate (3:1) applies
                    need = 3.0 if mark or size >= 18 or (cell.bold and size >= 14) else 4.5
                    if cr < need and (worst is None or cr / need < worst[0]):
                        worst = (cr / need, cr, need, text, cell.color_hex, bg, cell.fill_hex is None)
            if worst is None:
                continue
            _, cr, need, text, color, bg, _ = worst
            brand = color.upper() in palette and bg.upper() in palette and cr >= 3.0
            severity = "error" if cr < 2.5 else ("info" if brand else "warn")
            out.append(ctx.new_issue(TABLE_CONTRAST_LOW, s.index, f"контраст {cr:.1f}:1 у «{text[:30]}» в таблице (#{color} на #{bg}, нужно {need:g}:1)", bboxes=[e.bbox_frac], element_ids=[e.id], severity=severity, details={"contrast": round(cr, 2), "background": bg, "brand_pair": brand}))
    return out
