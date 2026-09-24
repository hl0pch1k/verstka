"""Regression tests for the clone renderer defects found in the adversarial review (R3, R4, R5, R7, R8, EXTRA-2/3/5/6).

Every case builds a small synthetic deck with python-pptx and a hand-written pattern, so the tests do not depend on
the template analyzer; the VK templates are only used by the integration-marked check at the end.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Pt

from verstka.analysis.xmlns import q
from verstka.ingest.workspace import TemplateWorkspace
from verstka.rendering.clone import _merge_items, render_clone
from verstka.rendering.deck import DeckBuilder, element_bbox, slide_shape_elements
from verstka.rendering.fit import fit_size
from verstka.rendering.renderer import render_deck
from verstka.rendering.textfill import shape_text
from verstka.schemas.common import Bbox, BboxFrac, Family, PatternKind, SlotRole
from verstka.schemas.layout import LayoutPlan, LayoutSlide
from verstka.schemas.outline import DeckOutline, NumberCallout, OutlineSlide, SlideContent, SlideItem, TableData
from verstka.schemas.template import FontUsage, Pattern, RepeatGroup, SlideSize, Slot, SlotStyle, Spacing, TemplateManifest, Tokens, TypeStep, Typography

W, H = 12192000, 6858000
DATASET = Path("/Users/h.u.1.l.a/Downloads/Конкурсы/VK tech/Датасет")


# ---------------------------------------------------------------------------- deck helpers


def _tb(slide, x, y, w, h, text="", *, size=14.0, bold=False, fill=None, zero_insets=True, name=None):
    """A text box (or a filled rectangle when fill is given) at fractional coordinates."""
    if fill is not None:
        sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(int(x * W)), Emu(int(y * H)), Emu(int(w * W)), Emu(int(h * H)))
        sh.fill.solid()
        sh.fill.fore_color.rgb = RGBColor.from_string(fill)
        sh.line.fill.background()
    else:
        sh = slide.shapes.add_textbox(Emu(int(x * W)), Emu(int(y * H)), Emu(int(w * W)), Emu(int(h * H)))
    tf = sh.text_frame
    tf.word_wrap = True
    if zero_insets:
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Emu(0)
    lines = text.split("\n") if text else [""]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.name = "Play"
    if name:
        sh.name = name
    return sh


def _pic(slide, img: Path, x, y, w, h):
    return slide.shapes.add_picture(str(img), Emu(int(x * W)), Emu(int(y * H)), Emu(int(w * W)), Emu(int(h * H)))


def _image(tmp_path: Path, name: str = "pic.png") -> Path:
    p = tmp_path / name
    if not p.exists():
        Image.new("RGB", (200, 200), (30, 120, 255)).save(p)
    return p


def _frac(sh) -> BboxFrac:
    return BboxFrac(x=sh.left / W, y=sh.top / H, w=sh.width / W, h=sh.height / H)


def _sid(sh) -> str:
    return str(sh.shape_id)


def _slot(sh, role: SlotRole, *, size=None, bold=False, group=None, sample=None, sid=None) -> Slot:
    sid = sid or _sid(sh)
    return Slot(id=f"{role.value}_{sid}", role=role, shape_id=sid, bbox=_frac(sh), style=SlotStyle(font_family="Play", size_pt=size, bold=bold), group_id=group, sample_text=sample)


def _group(gid: str, cells: list[list], axis: str, max_n: int, gap: float = 0.02) -> RepeatGroup:
    ids = [[_sid(s) if not isinstance(s, str) else s for s in cell] for cell in cells]
    first = [s for s in cells[0]]
    xs = [s.left for s in first if not isinstance(s, str)]
    ys = [s.top for s in first if not isinstance(s, str)]
    x2 = [s.left + s.width for s in first if not isinstance(s, str)]
    y2 = [s.top + s.height for s in first if not isinstance(s, str)]
    cb = BboxFrac(x=min(xs) / W, y=min(ys) / H, w=(max(x2) - min(xs)) / W, h=(max(y2) - min(ys)) / H)
    return RepeatGroup(id=gid, member_shape_ids=ids, max_n=max_n, axis=axis, gap=gap, cell_bbox=cb, rows=1 if axis == "row" else len(ids), cols=len(ids) if axis == "row" else 1)


def _pattern(pid: str, src: int, kind: PatternKind, slots: list[Slot], groups: list[RepeatGroup] | None = None) -> Pattern:
    return Pattern(id=pid, source_slide=src, kind=kind, family=Family.light, slots=slots, repeat_groups=groups or [])


def _manifest(patterns: list[Pattern], safe: BboxFrac | None = None) -> TemplateManifest:
    typo = Typography(
        families=[FontUsage(family="Play", weight=1.0)],
        scale=[TypeStep(role="display", size_pt=60), TypeStep(role="h1", size_pt=36), TypeStep(role="h2", size_pt=24), TypeStep(role="body", size_pt=16), TypeStep(role="small", size_pt=12), TypeStep(role="caption", size_pt=10)],
        sizes_used=[60, 48, 44, 36, 32, 24, 20, 18, 16, 14, 12, 10],
    )
    tokens = Tokens(typography=typo, spacing=Spacing(safe_area=safe or BboxFrac(x=0.05, y=0.08, w=0.90, h=0.84)))
    return TemplateManifest(template_id="synthetic", source_file="synthetic.pptx", slide_size=SlideSize(w=W, h=H), tokens=tokens, patterns=patterns, n_slides=1)


def _new_prs():
    prs = Presentation()
    prs.slide_width = Emu(W)
    prs.slide_height = Emu(H)
    return prs, prs.slide_layouts[6]


def _clone(pptx: Path, manifest: TemplateManifest, pattern: Pattern, oslide: OutlineSlide, tmp_path: Path):
    builder = DeckBuilder(pptx)
    ws = TemplateWorkspace.create(pptx, tmp_path / "ws")
    outline = DeckOutline(title="T", slides=[oslide])
    plan = LayoutSlide(outline_id=oslide.id, mode="clone", pattern_id=pattern.id)
    slide, warnings = render_clone(builder, plan, oslide, pattern, manifest, ws, outline)
    return slide, warnings, builder


def _texts(slide) -> dict[str, str]:
    return {sid: shape_text(el) for sid, el in slide_shape_elements(slide).items() if etree.QName(el).localname == "sp"}


def _paras(el) -> list[etree._Element]:
    return el.findall(".//" + q("a:p"))


def _is_bold(p: etree._Element) -> bool:
    r = p.find(".//" + q("a:rPr"))
    return r is not None and r.get("b") == "1"


def _has_bullet(p: etree._Element) -> bool:
    pPr = p.find(q("a:pPr"))
    return pPr is not None and pPr.find(q("a:buChar")) is not None


# ---------------------------------------------------------------------------- R3: native table box and header alignment


def test_r3_table_takes_grid_extent_and_stays_in_safe_area(tmp_path):
    prs, blank = _new_prs()
    s = prs.slides.add_slide(blank)
    title = _tb(s, 0.035, 0.06, 0.64, 0.17, "Заголовок", size=36)
    gf = s.shapes.add_table(3, 4, Emu(0), Emu(int(0.205 * H)), Emu(W), Emu(int(0.789 * H)))
    # Google-Slides export: the frame extent is a dummy 0.246×0.437 while gridCol/tr carry the real size
    xfrm = gf._element.find(q("p:xfrm"))
    xfrm.find(q("a:ext")).set("cx", str(int(0.246 * W)))
    xfrm.find(q("a:ext")).set("cy", str(int(0.437 * H)))
    pptx = tmp_path / "t.pptx"
    prs.save(pptx)
    safe = BboxFrac(x=0.035, y=0.062, w=0.929, h=0.804)
    pat = _pattern("p", 1, PatternKind.table, [_slot(title, SlotRole.title, size=36, sample="Заголовок"), _slot(gf, SlotRole.image)])
    manifest = _manifest([pat], safe=safe)
    table = TableData(columns=["Сценарий", "Базовый", "Про", "Кол-во"], rows=[["Напоминание", "да", "да", "12"], ["Эскалация", "нет", "да", "7"]])
    oslide = OutlineSlide(id="s7", kind=PatternKind.table, headline="Функциональность по тарифам", content=SlideContent(table=table))
    slide, warnings, _ = _clone(pptx, manifest, pat, oslide, tmp_path)
    frames = [sh for sh in slide.shapes if sh.has_table]
    assert len(frames) == 1, "the sample table is replaced by exactly one native table"
    t = frames[0]
    assert t.left >= int(safe.x * W) - 1 and t.left + t.width <= int(safe.x2 * W) + 1
    assert t.top + t.height <= int(safe.y2 * H) + 1
    assert t.width >= 0.8 * W, f"table must use the grid width, got {t.width / W:.3f} of the slide"
    # header alignment follows the column: labels left, да/нет columns centred (as ✓ / —), numeric columns right — same
    # as the body
    tbl = t.table
    assert tbl.cell(0, 1).text_frame.paragraphs[0].alignment == tbl.cell(1, 1).text_frame.paragraphs[0].alignment == PP_ALIGN.CENTER
    assert tbl.cell(0, 3).text_frame.paragraphs[0].alignment == tbl.cell(1, 3).text_frame.paragraphs[0].alignment == PP_ALIGN.RIGHT
    assert tbl.cell(0, 0).text_frame.paragraphs[0].alignment == PP_ALIGN.LEFT


# ---------------------------------------------------------------------------- R4: silently dropped content


def test_r4a_two_column_bullets_reach_the_list_slot(tmp_path):
    prs, blank = _new_prs()
    s = prs.slides.add_slide(blank)
    title = _tb(s, 0.02, 0.055, 0.44, 0.15, "Слайд", size=24)
    lst = _tb(s, 0.53, 0.35, 0.42, 0.30, "Пункт\nПункт\nПункт", size=14)
    pptx = tmp_path / "t.pptx"
    prs.save(pptx)
    pat = _pattern("p", 1, PatternKind.two_column, [_slot(title, SlotRole.title, size=24, sample="Слайд"), _slot(lst, SlotRole.bullet_list, size=14, sample="Пункт\nПункт\nПункт")])
    cols = [SlideItem(title="До", bullets=["Задачи живут в 4 инструментах", "Статус уточняют вручную", "Дедлайны срываются в 31% случаев"]), SlideItem(title="После", bullets=["Единый список задач", "Статус обновляется автоматически", "Срывы снизились до 12%"])]
    oslide = OutlineSlide(id="s8", kind=PatternKind.two_column, headline="До и после пилота", content=SlideContent(columns=cols))
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    text = _texts(slide)[_sid(lst)]
    for b in cols[0].bullets + cols[1].bullets:
        assert b in text, f"column bullet lost: {b!r}"
    ps = _paras(slide_shape_elements(slide)[_sid(lst)])
    heads = [p for p in ps if "".join(t.text or "" for t in p.iter(q("a:t"))) in ("До", "После")]
    assert len(heads) == 2 and all(_is_bold(p) and not _has_bullet(p) for p in heads)
    assert sum(1 for p in ps if _has_bullet(p)) == 6


def _process_deck(tmp_path: Path, n: int = 4, label_h: float = 0.32):
    prs, blank = _new_prs()
    s = prs.slides.add_slide(blank)
    title = _tb(s, 0.056, 0.10, 0.89, 0.16, "Заголовок", size=36)
    cells = []
    for i in range(n):
        x = 0.054 + i * 0.222
        num = _tb(s, x, 0.326, 0.071, 0.126, str(i + 1), size=32)
        lab = _tb(s, x, 0.488, 0.205, label_h, "Описание шага", size=12)
        cells.append((num, lab))
    pptx = tmp_path / "t.pptx"
    prs.save(pptx)
    slots = [_slot(title, SlotRole.title, size=36, sample="Заголовок")]
    for num, lab in cells:
        slots.append(_slot(num, SlotRole.number, size=32, group="g1", sample=num.text_frame.text))
        slots.append(_slot(lab, SlotRole.number_label, size=12, group="g1", sample="Описание шага"))
    group = _group("g1", [[num, lab] for num, lab in cells], "row", n, gap=0.017)
    return pptx, _pattern("p", 1, PatternKind.process, slots, [group]), cells


def test_r4b_number_label_cell_keeps_step_title(tmp_path):
    pptx, pat, cells = _process_deck(tmp_path)
    items = [SlideItem(title=f"Неделя {i + 1}", text=t) for i, t in enumerate(["Включаем для 20% компаний", "Раскатываем на всех", "Публикуем дайджесты", "Интеграция с календарём"])]
    oslide = OutlineSlide(id="s9", kind=PatternKind.process, headline="Запуск за три недели", content=SlideContent(items=items))
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    els = slide_shape_elements(slide)
    for i, (num, lab) in enumerate(cells):
        ps = _paras(els[_sid(lab)])
        texts = ["".join(t.text or "" for t in p.iter(q("a:t"))) for p in ps]
        assert texts[0] == f"Неделя {i + 1}" and _is_bold(ps[0]), f"step title lost in cell {i}: {texts}"
        assert items[i].text in texts[1:]
        assert shape_text(els[_sid(num)]).strip() == str(i + 1)


def test_r4c_title_subtitle_uses_empty_body_slot_below_title(tmp_path):
    prs, blank = _new_prs()
    s = prs.slides.add_slide(blank)
    title = _tb(s, 0.051, 0.426, 0.838, 0.242, "", size=60)
    sub = _tb(s, 0.054, 0.710, 0.411, 0.081, "", size=20)
    pptx = tmp_path / "t.pptx"
    prs.save(pptx)
    # roles.py labels the empty box under the title bullet_list, not subtitle
    pat = _pattern("p", 1, PatternKind.title, [_slot(title, SlotRole.title, size=60), _slot(sub, SlotRole.bullet_list, size=20)])
    oslide = OutlineSlide(id="s1", kind=PatternKind.title, headline="Умные напоминания", subtitle="Итоги пилота и план запуска")
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    # covers bind short words to the next one with a no-break space («и\u00a0план»): compare the words
    texts = {k: v.replace("\u00a0", " ") for k, v in _texts(slide).items()}
    assert texts[_sid(title)] == "Умные напоминания"
    assert texts.get(_sid(sub)) == "Итоги пилота и план запуска", texts


# ---------------------------------------------------------------------------- R5: numbers vs standalone number slots


def _kpi_labels_deck(tmp_path: Path):
    """VK Tech p46: a 4-row label group (icon + label) plus two standalone number slots of different size."""
    prs, blank = _new_prs()
    s = prs.slides.add_slide(blank)
    img = _image(tmp_path)
    title = _tb(s, 0.02, 0.055, 0.74, 0.14, "Заголовок", size=24)
    n_small = _tb(s, 0.776, 0.131, 0.20, 0.10, "1%", size=32)
    n_big = _tb(s, 0.599, 0.498, 0.22, 0.175, "10%", size=48)
    cells = []
    for i in range(4):
        y = 0.29 + i * 0.15
        icon = _pic(s, img, 0.049, y, 0.028, 0.049)
        lab = _tb(s, 0.111, y, 0.215, 0.044, "Пункт", size=14)
        cells.append((icon, lab))
    pptx = tmp_path / "t.pptx"
    prs.save(pptx)
    slots = [_slot(title, SlotRole.title, size=24, sample="Заголовок"), _slot(n_small, SlotRole.number, size=32, sample="1%"), _slot(n_big, SlotRole.number, size=48, sample="10%")]
    for icon, lab in cells:
        slots.append(_slot(icon, SlotRole.icon, group="g1"))
        slots.append(_slot(lab, SlotRole.card_body, size=14, group="g1", sample="Пункт"))
    group = _group("g1", [[icon, lab] for icon, lab in cells], "column", 4, gap=0.037)
    return pptx, _pattern("p", 1, PatternKind.big_number, slots, [group]), n_small, n_big, cells


def test_r5_three_kpis_on_two_standalone_slots_keep_every_value(tmp_path):
    pptx, pat, n_small, n_big, cells = _kpi_labels_deck(tmp_path)
    numbers = [NumberCallout(value="+34%", label="задач завершены в срок"), NumberCallout(value="2,1 ч", label="экономии в неделю"), NumberCallout(value="12 400", label="участников пилота")]
    oslide = OutlineSlide(id="s4", kind=PatternKind.stat_row, headline="Пилот подтвердил эффект", content=SlideContent(numbers=numbers))
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    els = slide_shape_elements(slide)
    texts = _texts(slide)
    for n in numbers:
        holder = [sid for sid, t in texts.items() if n.label in t]
        assert holder, f"label lost: {n.label!r}"
        assert n.value in texts[holder[0]], f"{n.value!r} must sit in the same cell as its label, got {texts[holder[0]]!r}"
        assert _is_bold(_paras(els[holder[0]])[0])
    for sid in (_sid(n_small), _sid(n_big)):
        assert sid not in texts or not texts[sid].strip(), "unused standalone number slots are cleaned up"
    assert not any("dropped" in w for w in warnings), warnings


def test_r5_big_number_prefers_largest_standalone_slot(tmp_path):
    pptx, pat, n_small, n_big, cells = _kpi_labels_deck(tmp_path)
    oslide = OutlineSlide(id="s10", kind=PatternKind.big_number, headline="Сотрудники готовы рекомендовать", content=SlideContent(numbers=[NumberCallout(value="91%", label="готовы рекомендовать")]))
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    texts = _texts(slide)
    assert texts[_sid(n_big)].strip() == "91%", texts
    assert not texts.get(_sid(n_small), "").strip()
    assert "готовы рекомендовать" in texts[_sid(cells[0][1])]


def test_r5_standalone_numbers_warn_when_items_outnumber_slots(tmp_path):
    prs, blank = _new_prs()
    s = prs.slides.add_slide(blank)
    title = _tb(s, 0.05, 0.08, 0.9, 0.12, "Заголовок", size=36)
    n1 = _tb(s, 0.05, 0.35, 0.3, 0.15, "43%", size=88, bold=True)
    n2 = _tb(s, 0.55, 0.35, 0.3, 0.15, "33%", size=44, bold=True)
    l1 = _tb(s, 0.05, 0.52, 0.3, 0.1, "пояснение", size=16)
    l2 = _tb(s, 0.55, 0.52, 0.3, 0.1, "пояснение", size=16)
    pptx = tmp_path / "t.pptx"
    prs.save(pptx)
    pat = _pattern("p", 1, PatternKind.stat_row, [_slot(title, SlotRole.title, size=36), _slot(n2, SlotRole.number, size=44, bold=True, sample="33%"), _slot(n1, SlotRole.number, size=88, bold=True, sample="43%"), _slot(l1, SlotRole.number_label, size=16), _slot(l2, SlotRole.number_label, size=16)])
    numbers = [NumberCallout(value="+34%", label="задач в срок"), NumberCallout(value="2,1 ч", label="экономии"), NumberCallout(value="12 400", label="участников")]
    oslide = OutlineSlide(id="s4", kind=PatternKind.stat_row, headline="Итоги", content=SlideContent(numbers=numbers))
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    texts = _texts(slide)
    # the largest slot gets the first figure and every dropped figure is reported
    assert texts[_sid(n1)].strip() == "+34%" and texts[_sid(n2)].strip() == "2,1 ч"
    assert any("12 400" in w or "1 " in w for w in warnings) and any("no slot" in w or "dropped" in w for w in warnings), warnings


def _two_numbers_per_cell_deck(tmp_path: Path):
    """Education p46: two cells (column) each = donut picture + two figures + one label; the second label lives in a companion group."""
    prs, blank = _new_prs()
    s = prs.slides.add_slide(blank)
    img = _image(tmp_path)
    title = _tb(s, 0.056, 0.10, 0.89, 0.094, "Примеры диаграмм", size=36)
    cells, labels_b = [], []
    for i in range(2):
        y = 0.087 + i * 0.42
        donut = _pic(s, img, 0.545, y, 0.182, 0.323)
        icon = _pic(s, img, 0.50, y + 0.1, 0.03, 0.05)
        na = _tb(s, 0.545, y + 0.10, 0.181, 0.112, "42%", size=44)
        nb = _tb(s, 0.743, y + 0.10, 0.181, 0.112, "32%", size=44)
        la = _tb(s, 0.583, y + 0.323, 0.105, 0.052, "пояснение", size=18)
        lb = _tb(s, 0.781, y + 0.323, 0.105, 0.052, "пояснение", size=18)
        cells.append((donut, icon, na, nb, la))
        labels_b.append(lb)
    pptx = tmp_path / "t.pptx"
    prs.save(pptx)
    slots = [_slot(title, SlotRole.title, size=36)]
    for donut, icon, na, nb, la in cells:
        slots += [_slot(donut, SlotRole.image, group="g1"), _slot(icon, SlotRole.icon, group="g1"), _slot(na, SlotRole.number, size=44, group="g1", sample="42%"), _slot(nb, SlotRole.number, size=44, group="g1", sample="32%"), _slot(la, SlotRole.number_label, size=18, group="g1", sample="пояснение")]
    for lb in labels_b:
        slots.append(_slot(lb, SlotRole.number_label, size=18, group="g2", sample="пояснение"))
    g1 = _group("g1", [[donut, icon, na, nb, la] for donut, icon, na, nb, la in cells], "column", 2, gap=0.043)
    g2 = _group("g2", [[lb] for lb in labels_b], "column", 2, gap=0.37)
    return pptx, _pattern("p", 1, PatternKind.stat_row, slots, [g1, g2]), cells, labels_b


def test_r5_cells_with_two_number_slots_take_consecutive_items(tmp_path):
    pptx, pat, cells, labels_b = _two_numbers_per_cell_deck(tmp_path)
    numbers = [NumberCallout(value="+34%", label="задач в срок"), NumberCallout(value="2,1 ч", label="экономии в неделю"), NumberCallout(value="12 400", label="участников пилота")]
    oslide = OutlineSlide(id="s4", kind=PatternKind.stat_row, headline="Итоги", content=SlideContent(numbers=numbers))
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    texts = _texts(slide)
    els = slide_shape_elements(slide)
    (d0, i0, na0, nb0, la0), (d1, i1, na1, nb1, la1) = cells
    assert texts[_sid(na0)].strip() == "+34%" and texts[_sid(la0)].strip() == "задач в срок"
    assert texts[_sid(nb0)].strip() == "2,1 ч" and texts[_sid(labels_b[0])].strip() == "экономии в неделю"
    assert texts[_sid(na1)].strip() == "12 400" and texts[_sid(la1)].strip() == "участников пилота"
    assert not texts.get(_sid(nb1), "").strip() and not texts.get(_sid(labels_b[1]), "").strip()
    assert not any("dropped" in w for w in warnings), warnings
    # EXTRA-6: the sample donuts (18% of the slide width) are stale pictures, the small icons are part of the card
    assert _sid(d0) not in els and _sid(d1) not in els, "stale chart pictures inside processed cells must go"
    assert _sid(i0) in els and _sid(i1) in els, "icon-sized pictures stay"


# ---------------------------------------------------------------------------- R8: explicit zero insets


def test_r8_fit_size_respects_insets_and_single_line_height():
    box = Bbox(x=0, y=0, w=int(0.215 * W), h=int(17.9 * 12700))
    tight = fit_size(["участников пилота"], box, "Play", 14.0, insets_emu=(0, 0, 0, 0), scale_sizes=[36, 24, 16, 14, 12, 10])
    assert tight.fits and tight.size_pt == 14.0
    default = fit_size(["участников пилота"], box, "Play", 14.0, scale_sizes=[36, 24, 16, 14, 12, 10])
    assert default.size_pt < 14.0, "with the PowerPoint default insets the same box is too low: the rule must come from the shape"
    # single line that fits the width and a usable height of at least the size is accepted even with line spacing 1.2
    tall = Bbox(x=0, y=0, w=int(0.215 * W), h=int(14.5 * 12700))
    assert fit_size(["участников пилота"], tall, "Play", 14.0, insets_emu=(0, 0, 0, 0), scale_sizes=[14, 12, 10], line_spacing=1.2).size_pt == 14.0


def test_r8_fill_uses_shape_insets(tmp_path):
    pptx, pat, n_small, n_big, cells = _kpi_labels_deck(tmp_path)
    prs = Presentation(str(pptx))
    for sh in prs.slides[0].shapes:
        if sh.has_text_frame and sh.text_frame.text == "Пункт":
            sh.height = Emu(int(17.9 * 12700))  # a one-line 14 pt label box with zero insets
    prs.save(pptx)
    items = [SlideItem(title=t) for t in ("участников пилота", "экономии в неделю", "задач в срок", "оценка удобства")]
    oslide = OutlineSlide(id="s5", kind=PatternKind.cards, headline="Итоги", content=SlideContent(items=items))
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    els = slide_shape_elements(slide)
    for _, lab in cells:
        rpr = els[_sid(lab)].find(".//" + q("a:rPr"))
        assert rpr.get("sz") in (None, "1400"), f"label shrunk to {rpr.get('sz')}"


# ---------------------------------------------------------------------------- EXTRA-2: failed clone must not leave a half slide


def test_extra2_failed_clone_is_rolled_back_before_synth(simple_deck, tmp_path, monkeypatch):
    from verstka.analysis.manifest import analyze_template
    import verstka.rendering.renderer as renderer

    manifest = analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    ws = TemplateWorkspace.open(manifest.template_id, tmp_path / "ws")
    pattern = manifest.patterns[0]
    slides = [OutlineSlide(id=f"sl{i}", kind=PatternKind.bullets, headline=f"Слайд {i}", content=SlideContent(bullets=["один", "два"])) for i in (1, 2, 3)]
    outline = DeckOutline(title="T", slides=slides)
    plan = LayoutPlan(strategy="structured", template_id=manifest.template_id, slides=[LayoutSlide(outline_id=s.id, mode="clone", pattern_id=pattern.id) for s in slides])

    def boom(builder, plan_slide, oslide, pattern, manifest, ws, outline):
        builder.clone_slide(pattern.source_slide)
        raise RuntimeError("half-filled clone")

    monkeypatch.setattr(renderer, "render_clone", boom)
    res = render_deck(outline, plan, manifest, ws, tmp_path / "deck.pptx")
    prs = Presentation(str(res.pptx_path))
    assert len(prs.slides) == 3
    markers = [s.notes_slide.notes_text_frame.text.strip().splitlines()[-1] for s in prs.slides]
    assert markers == ["[verstka:sl1]", "[verstka:sl2]", "[verstka:sl3]"]
    assert all(s.mode == "synth" for s in res.slides)

    # both renderers fail: the previous slide keeps its own marker
    calls = {"n": 0}
    real_synth = renderer.render_synth

    def synth_fails_on_second(builder, plan_slide, oslide, manifest, ws, outline):
        calls["n"] += 1
        if oslide.id == "sl2":
            raise RuntimeError("synth broken")
        return real_synth(builder, plan_slide, oslide, manifest, ws, outline)

    monkeypatch.setattr(renderer, "render_synth", synth_fails_on_second)
    res2 = render_deck(outline, plan, manifest, ws, tmp_path / "deck2.pptx")
    prs2 = Presentation(str(res2.pptx_path))
    markers2 = [s.notes_slide.notes_text_frame.text.strip().splitlines()[-1] for s in prs2.slides]
    assert markers2 == ["[verstka:sl1]", "[verstka:sl3]"]
    assert any("synth fallback failed" in w for w in res2.slides[1].warnings)


# ---------------------------------------------------------------------------- EXTRA-3: bullets as items


def test_extra3_merge_items_distributes_title_only_items():
    items = [SlideItem(title=f"Тезис {i}") for i in range(5)]
    merged = _merge_items(items, 2)
    assert len(merged) == 2
    assert all(not x.text for x in merged), [x.text for x in merged]
    got = [b for x in merged for b in ([x.title] if x.title and x.title not in x.bullets else []) + x.bullets]
    assert got == [f"Тезис {i}" for i in range(5)]
    assert max(len(x.bullets) + (1 if x.title and x.title not in x.bullets else 0) for x in merged) <= 3
    # items with text keep the old fold
    rich = [SlideItem(title="A", text="a"), SlideItem(title="B", text="b"), SlideItem(title="C", text="c")]
    assert len(_merge_items(rich, 2)) == 2 and "C: c" in _merge_items(rich, 2)[1].text


def _two_cards_deck(tmp_path: Path, cell_w: float = 0.42):
    prs, blank = _new_prs()
    s = prs.slides.add_slide(blank)
    title = _tb(s, 0.056, 0.10, 0.89, 0.094, "Заголовок", size=36)
    cards = [_tb(s, 0.056 + i * (cell_w + 0.02), 0.38, cell_w, 0.5, "текст", size=16) for i in range(2)]
    lst = _tb(s, 0.056, 0.25, 0.89, 0.1, "Список", size=14)
    pptx = tmp_path / "t.pptx"
    prs.save(pptx)
    slots = [_slot(title, SlotRole.title, size=36), _slot(lst, SlotRole.bullet_list, size=14, sample="Список")] + [_slot(c, SlotRole.card_body, size=16, group="g1", sample="текст") for c in cards]
    return pptx, _pattern("p", 1, PatternKind.cards, slots, [_group("g1", [[c] for c in cards], "row", 2)]), cards, lst


def test_extra3_bullets_into_two_cells_are_lists_not_title_plus_text(tmp_path):
    pptx, pat, cards, lst = _two_cards_deck(tmp_path)
    bullets = ["Каждый третий дедлайн срывается", "Ручные напоминания ставят 18%", "Менеджеры тратят 5 часов"]
    oslide = OutlineSlide(id="s3", kind=PatternKind.bullets, headline="Проблема", content=SlideContent(bullets=bullets))
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    els = slide_shape_elements(slide)
    # the row reflows to three narrower cells (one thesis each) instead of merging theses into lists
    row = sorted((e for e in els.values() if element_bbox(e) and abs(element_bbox(e)[1] - int(0.38 * 6858000)) < 20000), key=lambda e: element_bbox(e)[0])
    seen = []
    for e in row:
        for p in _paras(e):
            t = "".join(x.text or "" for x in p.iter(q("a:t")))
            if t:
                seen.append(t)
                assert not (_is_bold(p) and not _has_bullet(p)), f"bullet {t!r} became a card title"
    assert seen == bullets


def test_extra3_tiny_cells_do_not_swallow_bullets(tmp_path):
    pptx, pat, cards, lst = _two_cards_deck(tmp_path, cell_w=0.035)
    for s in pat.slots:
        if s.role == SlotRole.card_body:
            s.capacity.max_chars, s.capacity.max_lines = 4, 1
    bullets = ["Каждый третий дедлайн срывается", "Ручные напоминания ставят 18%", "Менеджеры тратят 5 часов"]
    oslide = OutlineSlide(id="s3", kind=PatternKind.bullets, headline="Проблема", content=SlideContent(bullets=bullets))
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    texts = _texts(slide)
    assert all(b in texts[_sid(lst)] for b in bullets), texts
    assert not any(b in texts.get(_sid(c), "") for c in cards for b in bullets)


# ---------------------------------------------------------------------------- EXTRA-5: "Вставить фото" box


def test_extra5_photo_placeholder_box_is_removed_with_its_text(tmp_path):
    prs, blank = _new_prs()
    s = prs.slides.add_slide(blank)
    card = _tb(s, 0.03, 0.04, 0.47, 0.83, "", fill="FFFFFF")
    title = _tb(s, 0.047, 0.066, 0.43, 0.146, "Заголовок", size=24)
    photo_box = _tb(s, 0.039, 0.455, 0.453, 0.406, "", fill="F7F9FC")
    ph = _tb(s, 0.215, 0.627, 0.095, 0.056, "Вставить\nфото", size=10)
    lst = _tb(s, 0.507, 0.131, 0.422, 0.727, "Пункт\nПункт", size=10)
    pptx = tmp_path / "t.pptx"
    prs.save(pptx)
    pat = _pattern("p", 1, PatternKind.bullets, [_slot(title, SlotRole.title, size=24, sample="Заголовок"), _slot(lst, SlotRole.bullet_list, size=10, sample="Пункт\nПункт"), _slot(ph, SlotRole.body, size=10, sample="Вставить\nфото")])
    oslide = OutlineSlide(id="s3", kind=PatternKind.bullets, headline="Проблема", content=SlideContent(bullets=["один", "два"]))
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    els = slide_shape_elements(slide)
    assert _sid(ph) not in els
    assert _sid(photo_box) not in els, "the empty box behind «Вставить фото» is a leftover"
    assert _sid(card) in els, "the card that holds the title stays"


# ---------------------------------------------------------------------------- R7: empty cells and companion groups


def test_r7_empty_cells_lose_anchor_shapes(tmp_path):
    prs, blank = _new_prs()
    s = prs.slides.add_slide(blank)
    title = _tb(s, 0.035, 0.334, 0.64, 0.27, "Спасибо за внимание", size=54)
    cells = []
    for i in range(2):
        x = 0.035 + i * 0.252
        circle = s.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(x * W)), Emu(int(0.666 * H)), Emu(int(0.068 * W)), Emu(int(0.122 * H)))
        circle.fill.solid()
        circle.fill.fore_color.rgb = RGBColor(0x60, 0x70, 0x80)
        name = _tb(s, x + 0.089, 0.666, 0.182, 0.122, "Имя Спикера,\nдолжность", size=16)
        cells.append((circle, name))
    pptx = tmp_path / "t.pptx"
    prs.save(pptx)
    slots = [_slot(title, SlotRole.title, size=54, sample="Спасибо за внимание")] + [_slot(n, SlotRole.card_body, size=16, group="g1", sample="Имя Спикера,\nдолжность") for _, n in cells]
    pat = _pattern("p", 1, PatternKind.thanks, slots, [_group("g1", [[c, n] for c, n in cells], "row", 3, gap=0.0)])
    oslide = OutlineSlide(id="s12", kind=PatternKind.thanks, headline="Спасибо за внимание", subtitle="Команда VK WorkSpace")
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    els = slide_shape_elements(slide)
    for circle, name in cells:
        assert _sid(name) not in els
        assert _sid(circle) not in els, "an avatar circle without its text is an orphan"


def _title_body_groups_deck(tmp_path: Path, with_icons: bool = False):
    prs, blank = _new_prs()
    s = prs.slides.add_slide(blank)
    img = _image(tmp_path)
    title = _tb(s, 0.035, 0.06, 0.64, 0.17, "Заголовок", size=36)
    heads, bodies, icons = [], [], []
    for i in range(3):
        x = 0.048 + i * 0.304
        if with_icons and i > 0:
            icons.append(_pic(s, img, x + 0.02, 0.21, 0.05, 0.09))
        heads.append(_tb(s, x, 0.318, 0.257, 0.045, "Заголовок", size=20))
        bodies.append(_tb(s, x, 0.414, 0.257, 0.3, "Текст\nТекст", size=12))
    pptx = tmp_path / "t.pptx"
    prs.save(pptx)
    slots = [_slot(title, SlotRole.title, size=36, sample="Заголовок")]
    slots += [_slot(h, SlotRole.card_body, size=20, group="g2", sample="Заголовок") for h in heads]
    slots += [_slot(b, SlotRole.card_body, size=12, group="g1", sample="Текст\nТекст") for b in bodies]
    slots += [_slot(ic, SlotRole.icon, group="g3") for ic in icons]
    groups = [_group("g1", [[b] for b in bodies], "row", 3, gap=0.047), _group("g2", [[h] for h in heads], "row", 3, gap=0.047)]
    if icons:
        groups.append(_group("g3", [[ic] for ic in icons], "row", 2, gap=0.25))
    return pptx, _pattern("p", 1, PatternKind.cards, slots, groups), heads, bodies, icons


def test_r7_aligned_title_and_body_groups_are_filled_together(tmp_path):
    pptx, pat, heads, bodies, icons = _title_body_groups_deck(tmp_path)
    items = [SlideItem(title=f"Сценарий {i}", text=f"Описание сценария {i}") for i in range(3)]
    oslide = OutlineSlide(id="s5", kind=PatternKind.cards, headline="Сценарии", content=SlideContent(items=items))
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    texts = _texts(slide)
    for i in range(3):
        assert texts[_sid(heads[i])].strip() == f"Сценарий {i}", texts
        assert texts[_sid(bodies[i])].strip() == f"Описание сценария {i}", texts
    # fewer items: both groups shrink together
    oslide2 = OutlineSlide(id="s5", kind=PatternKind.cards, headline="Сценарии", content=SlideContent(items=items[:2]))
    slide2, _, _ = _clone(pptx, _manifest([pat]), pat, oslide2, tmp_path / "b")
    els2 = slide_shape_elements(slide2)
    assert _sid(heads[2]) not in els2 and _sid(bodies[2]) not in els2
    assert shape_text(els2[_sid(heads[1])]).strip() == "Сценарий 1" and shape_text(els2[_sid(bodies[1])]).strip() == "Описание сценария 1"


def test_r7_icon_companion_cells_follow_the_text_group(tmp_path):
    pptx, pat, heads, bodies, icons = _title_body_groups_deck(tmp_path, with_icons=True)
    items = [SlideItem(title=f"Сценарий {i}", text=f"Описание {i}") for i in range(2)]
    oslide = OutlineSlide(id="s5", kind=PatternKind.cards, headline="Сценарии", content=SlideContent(items=items))
    slide, warnings, _ = _clone(pptx, _manifest([pat]), pat, oslide, tmp_path)
    els = slide_shape_elements(slide)
    assert _sid(icons[0]) in els, "the icon over the second (kept) cell stays"
    assert _sid(icons[1]) not in els, "the icon over the removed third cell is an orphan"
    # with three items nothing is orphaned and both icons stay
    items3 = items + [SlideItem(title="Сценарий 2", text="Описание 2")]
    oslide3 = OutlineSlide(id="s5", kind=PatternKind.cards, headline="Сценарии", content=SlideContent(items=items3))
    slide3, _, _ = _clone(pptx, _manifest([pat]), pat, oslide3, tmp_path / "c")
    els3 = slide_shape_elements(slide3)
    assert _sid(icons[0]) in els3 and _sid(icons[1]) in els3
    assert shape_text(els3[_sid(heads[2])]).strip() == "Сценарий 2"


# ---------------------------------------------------------------------------- integration: the VK templates


@pytest.mark.integration
@pytest.mark.skipif(not DATASET.is_dir() or not any(DATASET.glob("*.pptx")), reason="VK dataset not available")
def test_vk_templates_render_demo_outline_without_lost_content(tmp_path):
    from verstka.pipeline.generate import generate_variants

    outline = DeckOutline.model_validate_json((Path(__file__).resolve().parents[1] / "fixtures" / "outline_demo.json").read_text(encoding="utf-8"))
    for name in ("VK_WorkSpace_Клиентская_конференция_Шаблон_03.pptx", "Шаблон презентации VK Education.pptx", "VK Tech шаблон.pptx"):
        tpl = DATASET / name
        if not tpl.exists():
            continue
        out = tmp_path / tpl.stem[:8]
        res = generate_variants(tpl, outline=outline, out_dir=out / "out", workspace_root=out / "ws", use_llm=False, use_vlm=False, audit=False, autofix=False, exports=[], render_images=False, strategies=["structured"])
        deck = res.variants[0].out_dir / "deck.pptx"
        prs = Presentation(str(deck))
        assert len(prs.slides) == len(outline.slides)
        W_, H_ = prs.slide_width, prs.slide_height
        def _walk(shapes):
            for sh in shapes:
                if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                    yield from _walk(sh.shapes)
                elif sh.has_text_frame:
                    yield sh.text_frame.text

        texts = "\n".join(t for s in prs.slides for t in _walk(s.shapes)).replace("\u00a0", " ").replace("\x0b", " ")
        assert "Итоги пилота" in texts, f"{name}: title subtitle lost"
        for b in outline.slides[7].content.columns[0].bullets + outline.slides[7].content.columns[1].bullets:
            assert b in texts, f"{name}: two_column bullet lost: {b!r}"
        for n in outline.slides[3].content.numbers:
            assert n.value in texts, f"{name}: KPI lost: {n.value!r}"
        for it in outline.slides[8].content.items:
            assert it.title in texts, f"{name}: step title lost: {it.title!r}"
        for s in prs.slides:
            for sh in s.shapes:
                if sh.has_table:
                    assert sh.width >= 0.35 * W_ and sh.left >= 0, f"{name}: table squeezed to {sh.width / W_:.2f}"
                if sh.has_text_frame and "Вставить" in sh.text_frame.text:
                    raise AssertionError(f"{name}: placeholder text survived")
