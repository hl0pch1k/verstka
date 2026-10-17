"""Unseen templates, round 2 (2026-10-17): the colour of a line on a gradient or a photo ground is chosen — and judged
by the audit — on what lies under its letters, probe by probe (a plate under a line no ink reads on everywhere); the
figures under a change beside a table keep the body size; a data chart or table under an obstacle at one side of the
foot (a slanted triangle, a page number) takes a narrower, taller area when it reads larger there."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Pt

from verstka.analysis.manifest import analyze_template
from verstka.analysis.xmlns import q
from verstka.ingest.workspace import TemplateWorkspace
from verstka.rendering.compose import Canvas, Composer, Kit, Para, Run
from verstka.rendering.deck import DeckBuilder, element_bbox
from verstka.schemas.common import Bbox, PatternKind, contrast_ratio
from verstka.schemas.data import SlideData
from verstka.schemas.outline import ChartSpec, DeckOutline, InlineSeries, OutlineSlide, SlideContent, TableData


def _to_layout(layout, shape) -> None:
    """Move a shape drawn on a scratch slide into the layout (python-pptx draws on slides only)."""
    el = shape._element
    el.getparent().remove(el)
    layout.shapes._spTree.insert(2, el)


def _fill(shape, rgb: str, alpha: float | None = None) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(rgb)
    shape.line.fill.background()
    if alpha is not None:
        clr = shape._element.find(".//" + q("a:srgbClr"))
        etree.SubElement(clr, q("a:alpha")).set("val", str(int(alpha * 100000)))


def _ground_deck(path: Path) -> Path:
    """A layout: dark purple over the whole slide, a 20 % white circle at the left, an opaque white panel over the
    right half of the lower part."""
    prs = Presentation()
    W, H = prs.slide_width, prs.slide_height
    layout = prs.slide_layouts[6]
    scratch = prs.slides.add_slide(layout)
    ground = scratch.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, W, H)
    _fill(ground, "560043")
    circle = scratch.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(0.05 * W)), Emu(int(0.1 * H)), Emu(int(0.3 * W)), Emu(int(0.4 * H)))
    _fill(circle, "FFFFFF", 0.2)
    panel = scratch.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(int(0.5 * W)), Emu(int(0.6 * H)), Emu(int(0.5 * W)), Emu(int(0.4 * H)))
    _fill(panel, "FFFFFF")
    for sh in (panel, circle, ground):
        _to_layout(layout, sh)
    prs.save(str(path))
    return path


def _line(slide, x: float, y: float, w: float, text: str, color: str):
    W, H = slide.part.package.presentation_part.presentation.slide_width, slide.part.package.presentation_part.presentation.slide_height
    cv = Canvas(slide)
    return cv.text(Bbox(x=int(x * W), y=int(y * H), w=int(w * W), h=int(0.05 * H)), [Para([Run(text, 14.0, color, False, "Arial")])], name="Note")


def test_the_ground_under_letters_is_read_probe_by_probe_with_its_opacity(tmp_path):
    from verstka.rendering.layers import letter_grounds

    prs = Presentation(str(_ground_deck(tmp_path / "g.pptx")))
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tinted = _line(s, 0.08, 0.25, 0.25, "Строка над кругом", "FFFFFF")
    got = set(letter_grounds(s, tinted, "Arial"))
    assert "FFFFFF" not in got and got, "a 20 % white circle tints the purple, it is no white ground"
    assert all(contrast_ratio("FFFFFF", g) >= 4.5 for g in got)
    across = _line(s, 0.1, 0.7, 0.8, "Строка через тёмную половину и через белую панель справа от неё", "FFFFFF")
    got2 = letter_grounds(s, across, "Arial")
    assert "560043" in got2 and "FFFFFF" in got2


def test_a_line_no_ink_reads_on_everywhere_gets_a_plate_others_a_readable_colour(tmp_path):
    from verstka.rendering.synth import _ink_pass

    deck = _ground_deck(tmp_path / "g.pptx")
    manifest = analyze_template(deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    prs = Presentation(str(deck))
    s = prs.slides.add_slide(prs.slide_layouts[6])
    dark = _line(s, 0.08, 0.25, 0.3, "Тёмная строка на тёмном", "300030")
    across = _line(s, 0.1, 0.7, 0.8, "Строка через тёмную половину и через белую панель справа от неё", "FFFFFF")
    pal = SimpleNamespace(text="000000", text2="333333", bg="FFFFFF")
    warnings: list[str] = []
    _ink_pass(s, [dark, across], pal, manifest, warnings)
    dcol = dark.find(".//" + q("a:srgbClr")).get("val")
    assert contrast_ratio(dcol, "560043") >= 4.5, dcol
    plate = across.getprevious()
    assert plate is not None and (plate.find(".//" + q("p:cNvPr")).get("name") or "").startswith("Plate")
    fill = plate.find(".//" + q("a:solidFill") + "/" + q("a:srgbClr")).get("val")
    assert contrast_ratio(across.find(".//" + q("a:srgbClr")).get("val"), fill) >= 4.5
    pb, tb = element_bbox(plate), element_bbox(across)
    assert pb[0] <= tb[0] and pb[0] + pb[2] >= tb[0] + tb[2], "the text's box stands on its plate"


def test_the_audit_reads_the_ground_under_letters_as_the_renderer_does(tmp_path):
    from verstka.audit.checks.template import _letter_probes
    from verstka.rendering.layers import letter_grounds

    prs = Presentation(str(_ground_deck(tmp_path / "g.pptx")))
    s = prs.slides.add_slide(prs.slide_layouts[6])
    el = _line(s, 0.1, 0.7, 0.8, "Строка через тёмную половину и через белую панель справа от неё", "FFFFFF")
    prs.save(str(tmp_path / "deck.pptx"))
    sid = el.find(".//" + q("p:cNvPr")).get("id")
    manifest = SimpleNamespace(tokens=SimpleNamespace(typography=SimpleNamespace(primary_family="Arial")))
    ctx = SimpleNamespace(ir=SimpleNamespace(source=tmp_path / "deck.pptx"), manifest=manifest)
    got = _letter_probes(ctx, SimpleNamespace(index=len(prs.slides)), SimpleNamespace(id=sid))
    assert got == letter_grounds(Presentation(str(tmp_path / "deck.pptx")).slides[-1], next(e for e in Presentation(str(tmp_path / "deck.pptx")).slides[-1]._element.iter(q("p:sp")) if e.find(".//" + q("p:cNvPr")).get("id") == sid), "Arial")
    assert "FFFFFF" in got and "560043" in got


@pytest.fixture
def env(simple_deck, tmp_path):
    manifest = analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    ws = TemplateWorkspace.open(manifest.template_id, tmp_path / "ws")
    return simple_deck, manifest, ws


def test_the_figures_under_a_change_beside_a_table_keep_the_body_size(env):
    deck, manifest, _ = env
    t = TableData(columns=["Показатель", "Набор 2024", "Набор 2025"], rows=[["Студентов", "640", "1 100"], ["Дошли до конца", "71%", "76%"], ["Трудоустроены", "58%", "63%"]])
    o = OutlineSlide(id="t", kind=PatternKind.table, headline="Результаты первого набора", content=SlideContent(table=t))
    prs = Presentation(str(deck))
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    W, H = manifest.slide_size.w, manifest.slide_size.h
    c = Composer(slide, Kit(manifest, W, H, "FFFFFF"), o, DeckOutline(title="T", strategy="visual", slides=[o]), "visual", manifest)
    n0 = len(c.cv.tree)
    c.compose("table", Bbox(x=int(0.06 * W), y=int(0.22 * H), w=int(0.88 * W), h=int(0.6 * H)))
    cols = [el for el in list(c.cv.tree)[n0:] if (el.find(".//" + q("p:cNvPr")).get("name") or "").startswith("Takeaway")]
    assert cols
    sizes = [int(r.get("sz")) / 100 for r in cols[0].iter(q("a:rPr")) if r.get("sz")]
    assert min(sizes) >= c.kit.text_floor - 0.05, sizes


def _slanted_foot_deck(path: Path) -> Path:
    """A layout with a triangle along the foot (high at the right, low at the left) and a page number at the right."""
    prs = Presentation()
    W, H = prs.slide_width, prs.slide_height
    layout = prs.slide_layouts[6]
    scratch = prs.slides.add_slide(layout)
    ff = scratch.shapes.build_freeform(int(0.1 * W), H)
    ff.add_line_segments([(W, int(0.76 * H)), (W, H), (int(0.1 * W), H)])
    tri = ff.convert_to_shape()
    _fill(tri, "DDDDDD")
    num = scratch.shapes.add_textbox(Emu(int(0.8 * W)), Emu(int(0.81 * H)), Emu(int(0.15 * W)), Emu(int(0.06 * H)))
    num.text_frame.text = "7"
    for sh in (num, tri):
        _to_layout(layout, sh)
    prs.save(str(path))
    return path


def test_an_area_beside_a_slanted_foot_runs_down_where_the_slant_leaves_room(tmp_path):
    from verstka.rendering.synth import _taller_area

    prs = Presentation(str(_slanted_foot_deck(tmp_path / "f.pptx")))
    W, H = prs.slide_width, prs.slide_height
    s = prs.slides.add_slide(prs.slide_layouts[6])
    area = Bbox(x=int(0.03 * W), y=int(0.35 * H), w=int(0.92 * W), h=int(0.38 * H))  # above the triangle's top
    tall = _taller_area(s, area, int(0.9 * H), None, W, H)
    assert tall is not None and tall.x == area.x and tall.w < area.w and tall.h >= 1.12 * area.h
    # nowhere on the triangle
    from verstka.rendering.layers import art_layers, painted_share

    assert all(painted_share(lay, tall) <= 0.02 for lay in art_layers(s))


def test_a_long_series_takes_the_taller_area_when_its_plot_grows(tmp_path):
    from verstka.rendering.synth import _better_area

    deck = _slanted_foot_deck(tmp_path / "f.pptx")
    manifest = analyze_template(deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    prs = Presentation(str(deck))
    W, H = prs.slide_width, prs.slide_height
    s = prs.slides.add_slide(prs.slide_layouts[6])
    months = [f"м{i}" for i in range(1, 22)]
    spec = ChartSpec(type="line", categories=months, unit="млн ₽", series=[InlineSeries(name="Выручка", values=[300 + 6 * i for i in range(21)])])
    o = OutlineSlide(id="d", kind=PatternKind.chart, headline="Выручка растёт", content=SlideContent(chart=spec), takeaway="Сентябрь к сентябрю: 423 млн ₽ против 344 млн ₽",
                     footnote="Источник: Выручка.csv", data=SlideData(dataset_id="d", file="Выручка.csv"))
    outline = DeckOutline(title="T", strategy="structured", slides=[o])
    kit = Kit(manifest, W, H, "FFFFFF")
    area = Bbox(x=int(0.03 * W), y=int(0.4 * H), w=int(0.92 * W), h=int(0.33 * H))
    tall = Bbox(x=area.x, y=area.y, w=int(0.65 * W), h=int(0.5 * H))
    n0 = len(s._element.cSld.find(q("p:spTree")))
    warnings: list[str] = []
    got = _better_area(s, kit, o, outline, manifest, "chart_text", area, tall, None, warnings)
    assert got is tall, warnings
    assert len(s._element.cSld.find(q("p:spTree"))) == n0, "the trials leave nothing on the slide"
    assert not (o.notes or ""), "the trials leave the slide's plan as it was"


def test_a_badge_digit_is_read_on_its_own_circle_not_on_the_ground_around_it(tmp_path):
    from verstka.rendering.synth import unreadable_text_pass

    deck = _ground_deck(tmp_path / "g.pptx")
    manifest = analyze_template(deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    prs = Presentation(str(deck))
    s = prs.slides.add_slide(prs.slide_layouts[6])
    W, H = prs.slide_width, prs.slide_height
    badge = s.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(0.6 * W)), Emu(int(0.2 * H)), Emu(int(0.06 * W)), Emu(int(0.06 * W)))
    _fill(badge, "FFFFFF")
    badge.text_frame.text = "1"
    badge.text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor(0, 0, 0)
    badge.text_frame.paragraphs[0].runs[0].font.size = Pt(16)
    unreadable_text_pass(s, manifest)
    assert str(badge.text_frame.paragraphs[0].runs[0].font.color.rgb) == "000000", "a black digit on its white circle reads"
