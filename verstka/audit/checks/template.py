"""Template compliance checks: fonts, sizes, colours, layouts, chrome, contrast."""

from __future__ import annotations

import re

from typing import Optional

from verstka.analysis.chrome import shape_signature
from verstka.audit.checks.common import composite_hex, fill_alpha, fix, ground_of, is_chrome_like, is_template_chrome, ru_count, template_grounds, text_elements, text_height_needed_pt
from verstka.audit.registry import AuditContext, check
from verstka.schemas.audit import CheckSpec, Issue
from verstka.schemas.common import EMU_PER_PT, Bbox, Color, contrast_ratio

FONT_NOT_IN_TEMPLATE = CheckSpec(id="font_not_in_template", title="Шрифт не из шаблона или гарнитур больше двух", severity="error", category="template", description="Гарнитура рана отсутствует среди шрифтов шаблона (используемых, встроенных или шрифтов темы), либо на слайде больше двух гарнитур. Имена сравниваются без регистра и дефисов, начертание в имени — та же гарнитура («Bebas» и «Bebas Neue», «Montserrat-Regular» и «Montserrat»); ссылки на шрифты темы (+mj-lt, +mn-lt) раскрываются; номер слайда и колонтитулы шаблона не проверяются.")
SIZE_NOT_IN_SCALE = CheckSpec(id="size_not_in_scale", title="Размер шрифта не из шкалы шаблона", severity="warn", category="template", description="Размер шрифта отличается более чем на 0,75 пт от всех размеров, встречающихся в шаблоне. Крупные числа (значение с единицей, от наибольшего кегля шаблона или вдвое крупнее основного текста) — отдельная ступень шкалы: они не проверяются.")
COLOR_NOT_IN_PALETTE = CheckSpec(id="color_not_in_palette", title="Цвет не из палитры шаблона", severity="warn", category="template", description="Цвет текста или заливки отстоит от ближайшего цвета палитры шаблона больше чем на ΔE 6 и не является более светлым или тёмным вариантом цветного цвета палитры (тот же тон и насыщенность, как ряды оттенков темы в PowerPoint). Своими считаются и цвета, которые задают макеты и мастер шаблона, а также чёрный и белый; служебные элементы шаблона (номер слайда, колонтитулы) не проверяются.")
LAYOUT_NOT_FROM_TEMPLATE = CheckSpec(id="layout_not_from_template", title="Слайд собран не на макете из шаблона", severity="error", category="template", description="Слайд ссылается на макет, которого нет в пакете шаблона.")
CHROME_MOVED = CheckSpec(id="chrome_moved", title="Логотип или колонтитул сдвинуты с положенного места", severity="warn", category="template", description="Элемент хрома шаблона (логотип, колонтитул на слайдах) отсутствует или стоит в другом месте.")
TABLE_CONTRAST_LOW = CheckSpec(id="table_contrast_low", title="Контраст текста в таблице ниже нормы", severity="warn", category="template", description="Контраст по WCAG между текстом ячейки таблицы и её заливкой (или фоном слайда) ниже 4.5:1 для обычного текста и 3:1 для крупного (≥18 пт или ≥14 пт жирным) и для значков ✓ / —. Пара цветов шаблона (белый на фирменном синем) от 3:1 — только справка.")
CONTRAST_LOW = CheckSpec(id="contrast_low", title="Контраст текста к фону ниже 4.5:1", severity="warn", category="template", description="Контраст по WCAG между цветом текста и фоном ниже 4.5:1 для обычного текста и 3:1 для крупного (≥18 пт или ≥14 пт жирным). Фон — карточка слайда с учётом прозрачности заливки, иначе плашка, панель или картинка, которую рисуют макет и мастер шаблона, иначе фон слайда; градиент и картинка берутся в том месте, где стоит текст. На картинке или градиенте цвет фона — оценка: от 2:1 — сведение, ниже — ошибка. Строки, которые выходят за край своей плашки на другой фон (двухстрочный заголовок в однострочной полосе), проверяются и на том фоне; у текста на фигуре макета (треугольник, произвольная фигура) каждая строка проверяется по ширине своих букв — буквы, сошедшие с наклонного края на фон рядом, сравниваются с тем фоном.")

CONTRAST_CANDIDATE_ROLES = ("text.primary", "text.secondary")


def _norm_font(name: str) -> str:
    """«Bebas Neue» → «bebas neue», «Montserrat-Regular» → «montserrat regular»: lower case, separators as spaces."""
    return " ".join(re.sub(r"[-_]+", " ", (name or "").lower()).split())


def _theme_font(name: str, ctx: AuditContext) -> str:
    """A theme reference (+mj-lt, +mn-ea …) resolved through the deck's theme fonts."""
    tf = list(getattr(ctx.ir, "theme_fonts", []) or [])
    if name.startswith("+mj") and tf and tf[0]:
        return tf[0]
    if name.startswith("+mn") and len(tf) > 1 and tf[1]:
        return tf[1]
    return name


def same_family(a: str, b: str) -> bool:
    """Two names of one family: equal after normalisation, or one is the other plus more words and the shorter has
    at least 4 characters («Bebas» ≡ «Bebas Neue», «Open Sans» ≡ «Open Sans Light», «Montserrat» ≡ «Montserrat-Regular»)."""
    a, b = _norm_font(a), _norm_font(b)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 4 and long_.startswith(short + " ")


def _allowed_fonts(ctx: AuditContext) -> set[str]:
    typo = ctx.manifest.tokens.typography
    # anything the template itself uses, and the fonts of its theme (what its placeholders fall back to)
    fam = {f.family.lower() for f in typo.families if f.weight > 0 or getattr(f, "source", "text") == "theme"}
    fam |= {f.lower() for f in ctx.manifest.embedded_fonts}
    fam |= {f.lower() for f in ctx.ir.embedded_fonts}
    fam |= {f.lower() for f in (getattr(ctx.ir, "theme_fonts", []) or []) if f}
    # the stand-ins the renderer sets Russian text in where a template family has no Cyrillic (rendering/cyrillic.py)
    if ctx.ws is not None:
        try:
            from verstka.rendering.cyrillic import cyrillic_substitutes

            fam |= {v.lower() for v in cyrillic_substitutes(ctx.ws.source, extra=[f.family for f in typo.families]).values()}
        except Exception:  # noqa: BLE001 - the template's own families then
            pass
    return fam


def _font_groups(fonts: list[str]) -> list[list[str]]:
    """Fonts grouped by family (`same_family`), first appearance order."""
    groups: list[list[str]] = []
    for f in fonts:
        for g in groups:
            if any(same_family(f, x) for x in g):
                g.append(f)
                break
        else:
            groups.append([f])
    return groups


@check(FONT_NOT_IN_TEMPLATE)
def font_not_in_template(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    allowed = _allowed_fonts(ctx)
    if not allowed:
        return out
    for s in ctx.ir.slides:
        used: dict[str, list[str]] = {}
        for e in text_elements(s):
            if is_template_chrome(e, ctx.manifest):
                continue  # the template's own page number / footer keeps the template's own font
            for p in e.paragraphs:
                for r in p.runs:
                    if r.font and r.text.strip():
                        used.setdefault(_theme_font(r.font, ctx), []).append(e.id)
        bad = {f: ids for f, ids in used.items() if not f.startswith("+") and not any(same_family(f, a) for a in allowed)}
        for f, ids in bad.items():
            out.append(ctx.new_issue(FONT_NOT_IN_TEMPLATE, s.index, f"шрифт «{f}» отсутствует в шаблоне", element_ids=sorted(set(ids)), bboxes=[s.by_id(i).bbox_frac for i in sorted(set(ids))[:3] if s.by_id(i)], autofix=fix("refont", "заменить на основной шрифт шаблона", element_ids=sorted(set(ids)))))
        groups = _font_groups(list(used))
        if len(groups) > 2:
            out.append(ctx.new_issue(FONT_NOT_IN_TEMPLATE, s.index, f"на слайде {ru_count(len(groups), 'шрифт', 'шрифта', 'шрифтов')}: {', '.join(sorted(g[0] for g in groups))}", severity="warn"))
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
            if is_template_chrome(e, ctx.manifest):
                continue  # the template's own page number (a big «02») is set at the template's own size
            for p in e.paragraphs:
                for r in p.runs:
                    if r.size_pt and r.size_pt >= display_from and is_figure(r.text):
                        continue  # the display step of the scale: figures may be set larger than any text
                    if r.size_pt and r.text.strip() and all(abs(r.size_pt - t) > 0.75 for t in sizes):
                        bad.setdefault(r.size_pt, []).append(e.id)
        for sz, ids in bad.items():
            out.append(ctx.new_issue(SIZE_NOT_IN_SCALE, s.index, f"размер шрифта {sz:g} пт не из шкалы шаблона", element_ids=sorted(set(ids)), severity="info" if any(abs(sz - t) <= 2.0 for t in sizes) else "warn", details={"size": sz}))
    return out


SHADE_HUE = 4.0  # degrees
SHADE_SAT = 0.08
SHADE_MIN_SAT = 0.15


def is_shade_of(hex_: str, palette: list[str]) -> bool:
    """A lighter or darker variant of a chromatic palette colour — the same hue and saturation (HSL), only another
    lightness: what PowerPoint lists under each theme colour («Акцент 1, темнее 25%»). A greyed or re-hued colour is
    not one, and neither is a grey (every grey would be a «shade» of black)."""
    import colorsys

    def hsl(h: str) -> tuple[float, float, float]:
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
        return hh * 360.0, ss, ll

    try:
        h0, s0, l0 = hsl(hex_)
    except ValueError:
        return False
    if s0 < SHADE_MIN_SAT or not 0.08 <= l0 <= 0.92:
        return False
    for p in palette:
        try:
            h1, s1, _ = hsl(p)
        except ValueError:
            continue
        if s1 < SHADE_MIN_SAT:
            continue
        dh = abs(h0 - h1) % 360.0
        if min(dh, 360.0 - dh) <= SHADE_HUE and abs(s0 - s1) <= SHADE_SAT:
            return True
    return False


@check(COLOR_NOT_IN_PALETTE)
def color_not_in_palette(ctx: AuditContext) -> list[Issue]:
    out: list[Issue] = []
    palette = [Color(hex=h) for h in ctx.manifest.tokens.palette()]
    if not palette:
        return out
    # the colours the template's layouts and masters set themselves (its page-number grey, its text styles), and
    # pure black and white, are the template's own
    palette += [Color(hex=h) for h in dict.fromkeys(list(getattr(ctx.ir, "template_colors", []) or []) + ["000000", "FFFFFF"])]

    def nearest(hex_: str) -> float:
        c = Color(hex=hex_)
        return min(Color.delta_e(c, p) for p in palette)

    shades_of = [p.hex for p in palette]

    for s in ctx.ir.slides:
        seen: dict[str, list[str]] = {}
        for e in s.elements:
            if e.type == "chart":
                continue  # chart colours come from the palette by construction; sample charts are removed
            if is_template_chrome(e, ctx.manifest):
                continue
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
                if d > 6.0 and not is_shade_of(h, shades_of):
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


SPILL_LINE = 0.1  # share of a line height the text's lines may run past its band before it counts as spilling


def _line_band(e) -> Bbox:
    """The band the text's lines really fill at the box's anchor — not clipped to the box: an overflowing text runs
    past its box (down from a top anchor, both ways from a centre anchor, up from a bottom anchor)."""
    need, _ = text_height_needed_pt(e)
    h = max(int(need * EMU_PER_PT) + e.insets_emu[1] + e.insets_emu[3], 1)
    anchor = e.anchor or "t"
    y = e.bbox.y if anchor == "t" else (e.bbox.y2 - h if anchor == "b" else e.bbox.y + (e.bbox.h - h) // 2)
    return Bbox(x=e.bbox.x, y=y, w=e.bbox.w, h=h)


def _band_spill(s, e, bg_slide: str, color: str, size: float) -> Optional[tuple[float, str]]:
    """(contrast, ground) of the worst strip where the lines of a text that stands on a template band run past the
    band's top or bottom edge by more than SPILL_LINE of a line; None when they stay inside it."""
    grounds = template_grounds(s, e)
    if not grounds:
        return None
    band = min(grounds, key=lambda o: o.bbox.area)
    lines = e.bbox if e.autofit == "norm" else _line_band(e)  # a shrink-on-overflow box keeps its text inside it
    line_h = size * 1.2 * EMU_PER_PT
    strips = []
    if band.bbox.y - lines.y >= SPILL_LINE * line_h:
        strips.append(Bbox(x=lines.x, y=lines.y, w=lines.w, h=band.bbox.y - lines.y))
    if lines.y2 - band.bbox.y2 >= SPILL_LINE * line_h:
        strips.append(Bbox(x=lines.x, y=band.bbox.y2, w=lines.w, h=lines.y2 - band.bbox.y2))
    worst = None
    for strip in strips:
        probe = e.model_copy(update={"bbox": strip, "fill_hex": None})
        under = ground_of(s, probe, bg_slide)[0] or bg_slide
        try:
            cr = contrast_ratio(color, under)
        except ValueError:
            continue
        if worst is None or cr < worst[0]:
            worst = (cr, under)
    return worst


LINE_OFF = 0.08  # share of a line's letters off its shaped ground before the ground beside it counts


def _line_off_ground(s, e, bg_slide: str, color: str, need: float) -> Optional[tuple[float, str, str, float]]:
    """(contrast, ground, line) of the worst line of a text standing on a shaped template layer (a triangle, a
    freeform) whose letters leave that shape — measured line by line at the width each line really takes: a centred
    heading's second line may start on the white gap beside a slanted edge while the box as a whole stands on the
    triangle (LO Focus, gate 2 — C2). The ground there is the topmost other template layer painting it, else the
    slide's own ground. Returns (contrast, ground, line, share of the line's letters there) for the worst ground that
    lacks `need` under at least two samples of a line; None when every line keeps on its shape or on a ground it
    reads on."""
    from verstka.audit.checks.common import line_boxes
    from verstka.audit.checks.layout import _paints_at

    shaped = [o for o in template_grounds(s, e) if o.outline]
    if not shaped:
        return None
    band = shaped[-1]
    tpl = sorted((o for o in getattr(s, "template_elements", []) or [] if o is not band and o.fill_hex and o.type in ("shape", "text") and o.opaque), key=lambda o: (0 if o.source == "master" else 1, o.z))
    cache: dict = {}
    worst = None
    texts = [ln for p in e.paragraphs for ln in re.split(r"[\n\x0b]", p.text) if ln.strip()]
    for i, (box, _size) in enumerate(line_boxes(e)):
        nx = 48  # a letter is about 1/15 of a line: one at the end off the shape is seen
        pts = [(box.x + (k + 0.5) * box.w / nx, box.y + f * box.h) for k in range(nx) for f in (0.3, 0.5, 0.7)]
        off = [pt for pt in pts if not _paints_at(band, pt[0], pt[1])]
        if len(off) < 2:
            continue
        seen: dict[str, int] = {}
        for px, py in off:
            under = next((o.fill_hex.upper() for o in reversed(tpl) if _paints_at(o, px, py, None, cache)), None) or bg_slide
            seen[under] = seen.get(under, 0) + 1
        for under, n in seen.items():
            try:
                cr = contrast_ratio(color, under)
            except ValueError:
                continue
            if n < 2 or cr >= need:
                continue
            if worst is None or cr < worst[0]:
                worst = (cr, under, texts[i] if i < len(texts) else e.text, n / float(len(pts)))
    return worst


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
            enclosing, ground_kind = ground_of(s, e, bg_slide)
            under = enclosing or bg_slide
            # a ground of unknown colour: report, never recolour
            uncertain = enclosing is None and not s.background_hex
            # a picture or gradient ground (a layout photo, a gradient panel or background): its colour under the text
            # is only estimated (the region's mean, or the whole ground's median) — below 2:1 it is still an error,
            # above it a note, and it is never recoloured
            estimated = ground_kind in ("picture", "gradient") or (enclosing is None and (s.background_kind or "") in ("image", "gradient", "render"))
            try:
                bg = composite_hex(e.fill_hex, fill_alpha(e), under) if e.fill_hex else under
                cr = contrast_ratio(color, bg)
            except ValueError:
                continue
            size = e.dominant_size or 14.0
            bold = any(r.bold for p in e.paragraphs for r in p.runs if r.text.strip())
            need = 3.0 if size >= 18 or (bold and size >= 14) else 4.5  # WCAG: large text is 18 pt, or 14 pt bold
            spill = _band_spill(s, e, bg_slide, color, size) if ground_kind == "template" and not e.fill_hex else None
            if spill is not None and spill[0] < need:
                # the text is read on its band, but its lines run out of the band onto another ground (a two-line
                # heading in a one-line band: the second line white on white)
                cr2, under2 = spill
                out.append(ctx.new_issue(CONTRAST_LOW, s.index, f"строки «{e.text[:30]}» выходят за плашку шаблона: контраст {cr2:.1f}:1 (#{color} на #{under2})", bboxes=[e.bbox_frac], element_ids=[e.id], severity="error" if cr2 < 2.5 else "warn", details={"contrast": round(cr2, 2), "background": under2, "ground": "band_spill"}))
                continue
            off = _line_off_ground(s, e, bg_slide, color, need) if ground_kind == "template" and not e.fill_hex else None
            if off is not None:
                # the box stands on a triangle of the layout, but a line's letters run off its slanted edge onto the
                # ground beside it (white on the white gap): a letter or two at the edge — a warning, more — an error
                cr3, under3, line, share = off
                out.append(ctx.new_issue(CONTRAST_LOW, s.index, f"строка «{line[:30]}» выходит за фигуру шаблона на другой фон: контраст {cr3:.1f}:1 (#{color} на #{under3})", bboxes=[e.bbox_frac], element_ids=[e.id], severity="error" if cr3 < 2.5 and share >= LINE_OFF else "warn", details={"contrast": round(cr3, 2), "background": under3, "ground": "line_off_shape", "share": round(share, 3)}))
                continue
            if cr < need:
                accent_text = any(t.hex == color and any(r.startswith("accent.") for r in t.roles) for t in tokens.colors)
                severity = "error" if cr < 2.5 else ("info" if (accent_text and cr >= 3.0) else "warn")  # brand accent on dark is the template's own choice
                # the heading keeps the template's own colour (white on a pink pill is the design, not a slip)
                is_heading = e.ph_type in ("title", "ctrTitle")
                if is_heading and severity != "error":
                    severity = "info"
                to = None if uncertain or estimated or is_heading else _contrast_replacement(tokens, bg, need)
                autofix = fix("recolor", f"заменить цвет текста на #{to}", element_ids=[e.id], to=to, scope="text") if to else None
                if uncertain or (estimated and cr >= 2.0):
                    severity = "info"
                out.append(ctx.new_issue(CONTRAST_LOW, s.index, f"контраст {cr:.1f}:1 у «{e.text[:30]}» (#{color} на #{bg})", bboxes=[e.bbox_frac], element_ids=[e.id], severity=severity, details={"contrast": round(cr, 2), "background": bg, "ground": ground_kind or ("estimated" if estimated else "slide")}, autofix=autofix))
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
