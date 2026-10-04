"""Text measured as it is set, and composed content kept clear of the template's rules (round of 2026-10-04, QA on the
eight templates of the dev workspace):

* a heading over its text in one box is measured at its own step and weight, with the sample's space between the
  paragraphs (a WorkSpace card's last line hung under its plate);
* a box that sets no line spacing anywhere is single-spaced, whatever spacing the template's other texts use;
* the audit reads the spacing a paragraph inherits and the space between paragraphs;
* a rule of the layout through a composed area leaves the area its wider side; one on its edge pushes the edge in;
* a heading inherits its vertical anchor from the master through the layout;
* a mock-up slide shown alone keeps its first sentence as its lede; cards keep what a composed card holds;
* a cover of the author's text gets no invented date;
* the fixes of a finished deck (no markers in its notes) find their slides by the outline's order.
"""

from __future__ import annotations

from lxml import etree
from pptx import Presentation
from pptx.util import Emu, Inches, Pt

from verstka.analysis.xmlns import q
from verstka.schemas.common import EMU_PER_PT, Bbox

_CARD = """<p:sp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
  xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:nvSpPr><p:cNvPr id="5" name="Card"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
  <p:spPr><a:xfrm><a:off x="431800" y="1841500"/><a:ext cx="3636000" cy="2022000"/></a:xfrm>
    <a:prstGeom prst="roundRect"><a:avLst/></a:prstGeom><a:solidFill><a:srgbClr val="232323"/></a:solidFill></p:spPr>
  <p:txBody><a:bodyPr anchor="t" lIns="108000" tIns="72000" rIns="91425" bIns="45700" wrap="square"><a:noAutofit/></a:bodyPr><a:lstStyle/>
    <a:p><a:pPr><a:spcBef><a:spcPts val="0"/></a:spcBef></a:pPr><a:r><a:rPr lang="ru-RU" sz="2000" b="1"><a:latin typeface="Play"/></a:rPr><a:t>Первый этап развития</a:t></a:r></a:p>
    <a:p><a:pPr><a:spcBef><a:spcPts val="600"/></a:spcBef></a:pPr><a:r><a:rPr lang="ru-RU" sz="1800"><a:latin typeface="Play"/></a:rPr><a:t>{body}</a:t></a:r></a:p>
  </p:txBody></p:sp>"""

_LONG = ("Повышение надежности: проверка датчиков, контроль фактического расхода воды, резервное питание контроллера "
         "и удобный журнал событий.")


def test_a_heading_over_its_text_is_measured_as_set():
    from verstka.rendering.fit import fit_size

    texts = ["Первый этап развития", _LONG]
    box = Bbox(x=0, y=0, w=int(286.3 * EMU_PER_PT), h=int(159.2 * EMU_PER_PT))
    ins = (108000, 72000, 91425, 45700)
    plain = fit_size(texts, box, "Play", 18.0, False, [], insets_emu=ins, line_spacing=1.2, min_ratio=0.6)
    as_set = fit_size(texts, box, "Play", 18.0, False, [], insets_emu=ins, line_spacing=1.2, para_spacing_pt=6.0, min_ratio=0.6, head=(20 / 18, True))
    assert as_set.height_pt > plain.height_pt + 6.0 - 0.01 or as_set.size_pt < plain.size_pt
    # set at the size it was fitted, the heading and the text keep inside the card's inner height
    inner = (box.h - ins[1] - ins[3]) / EMU_PER_PT
    assert as_set.fits and as_set.height_pt <= inner


def test_ink_box_counts_the_space_between_paragraphs():
    from verstka.rendering.clone_check import ink_box

    sp = etree.fromstring(_CARD.format(body=_LONG))
    with_gap = ink_box(sp, "Play")
    sp2 = etree.fromstring(_CARD.format(body=_LONG).replace('<a:spcPts val="600"/>', '<a:spcPts val="0"/>'))
    without = ink_box(sp2, "Play")
    assert with_gap is not None and without is not None
    assert abs((with_gap.h - without.h) / EMU_PER_PT - 6.0) < 0.05


def _composed_rule_slide(tmp_path):
    """A slide on a layout that draws a hairline down the middle of the slide (the line moved from a scratch slide
    into the layout's own shape tree: python-pptx draws no shapes on layouts)."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    layout = prs.slide_layouts[6]
    W, H = prs.slide_width, prs.slide_height
    scratch = prs.slides.add_slide(layout)
    line = scratch.shapes.add_connector(1, W // 2, int(0.06 * H), W // 2, int(0.94 * H))
    line.line.width = Pt(1)
    layout.shapes._spTree.append(line._element)
    slide = prs.slides.add_slide(layout)
    return prs, slide, W, H


def test_a_rule_through_the_area_leaves_its_wider_side(tmp_path):
    from verstka.rendering.layers import clear_of_rules

    prs, slide, W, H = _composed_rule_slide(tmp_path)
    area = Bbox(x=int(0.44 * W), y=int(0.3 * H), w=int(0.45 * W), h=int(0.6 * H))
    got = clear_of_rules(slide, area)
    assert got.x > W // 2 and got.x2 == area.x2 and got.h == area.h


def test_a_rule_on_the_edge_of_the_area_pushes_the_edge_in(tmp_path):
    from verstka.rendering.layers import clear_of_rules

    prs, slide, W, H = _composed_rule_slide(tmp_path)
    area = Bbox(x=int(0.05 * W), y=int(0.15 * H), w=int(0.455 * W), h=int(0.7 * H))  # its right edge a hair past the rule
    got = clear_of_rules(slide, area)
    assert got.x == area.x and got.x2 < W // 2 - int(0.01 * W)


def test_a_heading_inherits_its_anchor_from_the_master():
    from verstka.rendering.synth import _title_anchor

    prs = Presentation()
    master = prs.slide_master
    for ph in master.placeholders:
        if "TITLE" in str(ph.placeholder_format.type):
            ph.text_frame._txBody.find(q("a:bodyPr")).set("anchor", "b")
    layout = prs.slide_layouts[5]  # «Title Only»: its own title sets no anchor
    for ph in layout.placeholders:
        if "TITLE" in str(ph.placeholder_format.type):
            bp = ph.text_frame._txBody.find(q("a:bodyPr"))
            if bp is not None and bp.get("anchor"):
                del bp.attrib["anchor"]
    slide = prs.slides.add_slide(layout)
    title = slide.shapes.title
    assert _title_anchor(title) == "b"


def test_a_mockup_shown_alone_keeps_its_first_sentence():
    from verstka.planning import faithful as F

    r = F.read_slide(8, "Панель наблюдения", "Панель управления объединяет текущие показания. Пользователь быстро видит, какие зоны требуют внимания.\n\n"
                     "[Место под изображение: экран панели управления теплицей]")
    room = F.Room()
    room.kinds.add("mockup")
    room.side_text["mockup"] = 0  # the template's screen stands alone under its heading
    forms = F.forms_of(r, room, "visual")
    f = forms[0]
    assert f.kind == "mockup" and not f.slide.content.bullets
    assert f.slide.subtitle and f.slide.subtitle.startswith("Панель управления объединяет текущие показания")


def test_cards_keep_what_a_composed_card_holds():
    from verstka.planning import faithful as F

    paras = ["Условия внутри теплицы меняются в течение дня. Солнечным утром температура может быстро расти, после "
             "проветривания — снижаться, а влажность грунта зависит от полива.",
             "Ручной полив часто выполняется по расписанию. Такой подход прост, но не всегда соответствует потребностям растений.",
             "В учебном проекте уход занимал в среднем 45 минут в день. В это время входили осмотр растений и полив.",
             "Автоматизация позволяет перейти к непрерывному наблюдению. Человек продолжает отвечать за растения."]
    r = F.read_slide(3, "Почему теплице нужен контроль", "\n\n".join(paras))
    room = F.Room()
    room.kinds.add("cards")
    room.cells["cards"] = [(4, 4, 90)]  # the template's card samples hold ninety characters a cell
    form = next(f for f in F.forms_of(r, room, "structured") if f.kind == "cards")
    texts = [i.text for i in form.slide.content.items]
    assert len(texts) == 4 and all(t.count(". ") >= 1 for t in texts), texts  # two sentences each, not the first alone


def test_a_cover_of_the_authors_text_gets_no_invented_date():
    from types import SimpleNamespace

    from verstka.rendering.clone import _bookend_texts, _deck_date
    from verstka.schemas.common import PatternKind
    from verstka.schemas.outline import DeckOutline, OutlineSlide

    for verbatim in (True, False):
        cover = OutlineSlide(id="sl1", kind=PatternKind.title, headline="Умная теплица", subtitle="Автоматизация полива", verbatim=verbatim)
        ctx = SimpleNamespace(outline=DeckOutline(title="Умная теплица", slides=[cover], language="ru"))
        footer = _bookend_texts(ctx, cover)[3]
        assert footer == (None if verbatim else _deck_date("ru"))


def test_the_fixes_of_a_finished_deck_find_their_slides_by_order(tmp_path):
    from verstka.audit.autofix import _ir_slides
    from verstka.schemas.audit import AuditReport
    from verstka.schemas.common import PatternKind
    from verstka.schemas.outline import DeckOutline, OutlineSlide

    prs = Presentation()
    for _ in range(2):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        s.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text_frame.text = "Текст"
    deck = tmp_path / "deck.pptx"
    prs.save(str(deck))
    outline = DeckOutline(title="Т", slides=[OutlineSlide(id="a", kind=PatternKind.bullets, headline="Один"), OutlineSlide(id="b", kind=PatternKind.bullets, headline="Два")])
    report = AuditReport(deck=str(deck), template_id="t", strategy="structured")
    assert [s.outline_id for s in _ir_slides(report, outline)] == ["a", "b"]
    assert [s.outline_id for s in _ir_slides(report)] == [None, None]


def test_the_audit_reads_inherited_spacing_and_paragraph_gaps(tmp_path):
    from verstka.audit.checks.common import text_elements, text_height_needed_pt
    from verstka.audit.ir import build_deck_ir

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(3))
    tf = tb.text_frame
    tf.text = "Первый"
    p2 = tf.add_paragraph()
    p2.text = "Второй"
    for p in tf.paragraphs:
        p.runs[0].font.size = Pt(20)
    lst = tf._txBody.find(q("a:lstStyle"))
    lvl = etree.SubElement(lst, q("a:lvl1pPr"))
    ln = etree.SubElement(lvl, q("a:lnSpc"))
    etree.SubElement(ln, q("a:spcPct")).set("val", "150000")
    sb = etree.SubElement(lvl, q("a:spcBef"))
    etree.SubElement(sb, q("a:spcPts")).set("val", "1000")
    deck = tmp_path / "deck.pptx"
    prs.save(str(deck))
    ir = build_deck_ir(deck, with_images=False)
    e = next(x for x in text_elements(ir.slides[0]) if "Первый" in x.text)
    assert all(abs((p.line_spacing or 0) - 1.5) < 1e-6 for p in e.paragraphs)
    need, lines = text_height_needed_pt(e)
    assert lines == 2 and abs(need - (2 * 20 * 1.2 * 1.5 + 10)) < 0.01
