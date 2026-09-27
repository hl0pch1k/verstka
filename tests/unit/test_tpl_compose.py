"""Composer / synth on third-party templates (TEMPLATE_FIX_PLAN, owner B): a word too wide for its box never becomes
a coordinate past the slide (T04), headings are capped and keep their inherited geometry (T01/T03/T05), sizes follow
the slide on a sparse template (T02/T09), dense blocks stay inside their area (T10), engine text never inherits the
template's capitals or tracking (T14), shape ids stay unique (T16)."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Pt

from verstka.analysis.manifest import analyze_template
from verstka.analysis.xmlns import q
from verstka.ingest.workspace import TemplateWorkspace
from verstka.rendering.charts import add_chart, chart_text_capped, short_categories
from verstka.rendering.compose import Canvas, Kit, Para, Run
from verstka.rendering.deck import DeckBuilder, element_bbox
from verstka.rendering.fit import fit_size
from verstka.rendering.synth import _title_style, deck_style, render_synth
from verstka.schemas.common import EMU_PER_PT, Bbox, PatternKind
from verstka.schemas.layout import LayoutSlide
from verstka.schemas.outline import ChartSpec, DeckOutline, InlineSeries, NumberCallout, OutlineSlide, SlideContent, SlideItem, TableData

LO_W, LO_H = 10078720, 5669280  # 11.02 × 6.2 in: a LibreOffice template
BIG_W, BIG_H = 24384000, 13716000  # 26.67 × 15 in


def _style_runs(tf, size: float, bold: bool = False, color: RGBColor = RGBColor(0x22, 0x22, 0x22)) -> None:
    for p in tf.paragraphs:
        for r in p.runs:
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = color
            r.font.name = "Arial"


def build_sparse_deck(path: Path, w: int = LO_W, h: int = LO_H, title_pt: float = 44, body_pt: float = 32) -> Path:
    """A LibreOffice-like template: its own type scale is two sizes (a 44 pt title, a 32 pt body placeholder)."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(w), Emu(h)
    s1 = prs.slides.add_slide(prs.slide_layouts[0])
    s1.shapes.title.text = "Company presentation"
    _style_runs(s1.shapes.title.text_frame, title_pt * 1.2, True)
    s1.placeholders[1].text = "Subtitle of the deck"
    _style_runs(s1.placeholders[1].text_frame, body_pt)
    for n in range(2):
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = f"Slide title {n + 1}"
        _style_runs(s.shapes.title.text_frame, title_pt, True)
        body = s.placeholders[1].text_frame
        body.text = "First point of the slide"
        body.add_paragraph().text = "Second point of the slide"
        _style_runs(body, body_pt)
    prs.save(path)
    return path


@pytest.fixture
def sparse_env(tmp_path):
    deck = build_sparse_deck(tmp_path / "sparse.pptx")
    manifest = analyze_template(deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    ws = TemplateWorkspace.open(manifest.template_id, tmp_path / "ws")
    return deck, manifest, ws


@pytest.fixture
def big_env(tmp_path):
    deck = build_sparse_deck(tmp_path / "big.pptx", BIG_W, BIG_H, title_pt=100, body_pt=25)
    manifest = analyze_template(deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    ws = TemplateWorkspace.open(manifest.template_id, tmp_path / "ws")
    return deck, manifest, ws


def _render(env, slides: list[OutlineSlide], comp: str, strategy: str = "structured"):
    deck, manifest, ws = env
    b = DeckBuilder(deck)
    outline = DeckOutline(title="T", strategy=strategy, slides=slides)
    out = []
    for o in slides:
        out.append(render_synth(b, LayoutSlide(outline_id=o.id, mode="synth", composition=comp), o, manifest, ws, outline))
    return b, out


def _boxes(slide):
    for el in slide._element.cSld.find(q("p:spTree")):
        if etree.QName(el).localname in ("sp", "pic", "graphicFrame", "cxnSp", "grpSp"):
            b = element_bbox(el)
            if b:
                yield el, b


# ---------------------------------------------------------------------------------------------- T04 fit


def test_fit_size_never_returns_a_sentinel_height_for_a_word_too_wide():
    box = Bbox(x=0, y=0, w=int(1.2 * 914400), h=int(1.0 * 914400))
    res = fit_size(["рентабельность"], box, "Play", 40.0, False, [40, 32, 24])
    assert res.broken_word and not res.fits
    assert res.height_pt < 40 * 1.2 * 20  # finite: the pieces the word is broken into, never 10^6 lines
    ok = fit_size(["Выручка"], Bbox(x=0, y=0, w=4 * 914400, h=914400), "Play", 24.0, False, [24, 20])
    assert ok.fits and not ok.broken_word


def test_fit_size_ladder_only_tries_no_off_scale_ratio_sizes():
    box = Bbox(x=0, y=0, w=int(2.0 * 914400), h=int(0.3 * 914400))
    text = ["Длинный заголовок, который не помещается в одну строку"]
    free = fit_size(text, box, "Play", 30.0, False, [30, 26.5, 23.5], min_ratio=0.5)
    ladder = fit_size(text, box, "Play", 30.0, False, [30, 26.5, 23.5], min_ratio=0.5, ladder_only=True)
    assert ladder.size_pt in (30.0, 26.5, 23.5)
    assert free.size_pt <= ladder.size_pt


# ---------------------------------------------------------------------------------------------- T04 / T16 canvas


def test_canvas_clamps_boxes_to_the_slide_and_reports_it(simple_deck):
    b = DeckBuilder(simple_deck)
    slide = b.add_blank_slide(6)
    cv = Canvas(slide, font="Arial")
    W, H = b.slide_w, b.slide_h
    cv.text(Bbox(x=int(0.9 * W), y=int(0.95 * H), w=int(0.3 * W), h=int(10 ** 11)), [Para([Run("Текст", 12.0, "000000")])], name="Legend")
    el = cv.added[-1]
    x, y, w, h = element_bbox(el)
    assert 0 <= x and x + w <= W and 0 <= y and y + h <= H
    assert any("clamped" in m for m in cv.clamp_warnings())


def test_canvas_ids_stay_unique_after_a_chart(simple_deck):
    from verstka.schemas.template import ChartStyleSpec, Typography

    b = DeckBuilder(simple_deck)
    slide = b.add_blank_slide(6)
    cv = Canvas(slide, font="Arial")
    cv.text(Bbox(x=0, y=0, w=914400, h=914400), [Para([Run("До графика", 12.0, "000000")])])
    outline = DeckOutline(title="T", slides=[])
    spec = ChartSpec(type="column", categories=["A", "B", "C"], series=[InlineSeries(name="S", values=[1, 2, 3])])
    add_chart(slide, Bbox(x=0, y=914400, w=4 * 914400, h=3 * 914400), spec, outline, ChartStyleSpec(), Typography())
    cv.text(Bbox(x=0, y=0, w=914400, h=914400), [Para([Run("После графика", 12.0, "000000")])])
    ids = [el.get("id") for el in slide._element.iter(q("p:cNvPr"))]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------------------------- T02 / T09 sizes


def test_sparse_template_sizes_follow_the_slide(sparse_env):
    _, manifest, _ = sparse_env
    typo = manifest.tokens.typography
    if not getattr(typo, "derived_sizes", None):
        pytest.skip("the analysis does not derive a ladder yet (contract C3)")
    kit = Kit(manifest, LO_W, LO_H, "FFFFFF")
    hpt = LO_H / EMU_PER_PT
    assert kit.body <= 0.031 * hpt + 0.5  # not the 32 pt placeholder body
    assert kit.small <= 0.025 * hpt + 0.5
    assert chart_text_capped(typo, 24.0, LO_H)


def test_chart_text_capped_only_for_large_or_sparse(simple_deck):
    from verstka.schemas.template import Typography

    assert not chart_text_capped(Typography(), 12.0, 6858000)  # 12 pt on a 540 pt slide: a dataset size
    assert chart_text_capped(Typography(), 24.0, LO_H)  # a bullet placeholder's 24 pt on an 11″ slide


def test_capped_chart_text_is_at_most_a_fortieth_of_the_slide(sparse_env):
    from verstka.schemas.template import ChartStyleSpec

    deck, manifest, _ = sparse_env
    b = DeckBuilder(deck)
    slide = b.add_blank_slide(6)
    outline = DeckOutline(title="T", slides=[])
    spec = ChartSpec(type="line", categories=[f"{i}-й месяц" for i in range(1, 7)], series=[InlineSeries(name="Выручка", values=[900, 950, 1000, 1050, 1100, 1138])])
    gf = add_chart(slide, Bbox(x=0, y=0, w=int(0.4 * LO_W), h=int(0.5 * LO_H)), spec, outline, ChartStyleSpec(font_size_pt=24.0), manifest.tokens.typography)
    sizes = [int(x.get("sz")) / 100 for x in gf.chart._chartSpace.iter() if etree.QName(x).localname in ("defRPr", "rPr") and x.get("sz")]
    assert sizes and max(sizes) <= 0.03 * LO_H / EMU_PER_PT + 0.5
    cats = [pt.text for pt in gf.chart._chartSpace.iter("{http://schemas.openxmlformats.org/drawingml/2006/chart}v")]
    assert not any("⁠" in (c or "") for c in cats)


def test_short_categories_without_joiner():
    assert "⁠" not in "".join(short_categories(["1-й месяц", "2-й месяц"], joiner=False))
    assert "⁠" in "".join(short_categories(["1-й месяц", "2-й месяц"]))  # the default keeps today's labels


# ---------------------------------------------------------------------------------------------- T03 headings


def test_display_sized_headings_are_capped(big_env):
    deck, manifest, _ = big_env
    b = DeckBuilder(deck)
    slides = [OutlineSlide(id=f"s{i}", kind=PatternKind.bullets, headline="Выручка вырастет на 26,5% за шесть месяцев работы кофейни", content=SlideContent(bullets=["Пункт"])) for i in range(3)]
    ds = deck_style(b, manifest, DeckOutline(title="T", slides=slides))
    hpt = BIG_H / EMU_PER_PT
    assert ds.head_size <= 0.062 * hpt + 0.5  # a 100 pt title on a 15″ slide is a display size, not a heading
    assert ds.head_size >= 0.04 * hpt


def test_heading_keeps_inherited_geometry_and_never_jumps_to_x0(sparse_env):
    _, manifest, _ = sparse_env
    o = OutlineSlide(id="a", kind=PatternKind.bullets, headline="Ежемесячные расходы кофейни составляют 780 000 рублей", content=SlideContent(bullets=["Продукты", "Зарплаты", "Аренда"]))
    _, [(slide, warnings)] = _render(sparse_env, [o], "bullets")
    title = next(sh for sh in slide.shapes if sh.is_placeholder)
    assert title.left is not None and title.left > 0.02 * LO_W
    assert title.top + title.height <= 0.45 * LO_H


# ---------------------------------------------------------------------------------------------- T10 dense blocks


def _dense_slides() -> list[tuple[str, OutlineSlide]]:
    steps = [SlideItem(title=f"{i}-й месяц", text=f"Запуск направления номер {i} и обучение сотрудников кофейни") for i in range(1, 7)]
    cards = [SlideItem(title=f"Сценарий развития {i}", text="Описание сценария в две-три строки текста для проверки плотного блока") for i in range(1, 7)]
    table = TableData(columns=["Показатель", "Сейчас", "Цель", "Разница"], rows=[[f"Строка {i}", f"{i * 100} ₽", f"{i * 120} ₽", f"+{i * 20} ₽"] for i in range(1, 9)])
    pie = ChartSpec(type="pie", categories=["Витрина для десертов", "Программа лояльности и учёт", "Обновление меню и фотографии", "Обучение сотрудников", "Резерв"], series=[InlineSeries(name="Вложения", values=[70000, 34000, 25000, 20000, 30000])], unit="₽")
    line = ChartSpec(type="line", categories=["Сейчас"] + [f"{i}-й месяц" for i in range(1, 7)], series=[InlineSeries(name="Выручка", values=[900, 950, 1000, 1050, 1100, 1120, 1138])], unit="тыс. ₽")
    head = "Выручка вырастет на 26,5% за шесть месяцев"
    return [
        ("process", OutlineSlide(id="p", kind=PatternKind.timeline, headline=head, content=SlideContent(items=steps, bullets=["Бюджет запуска — 180 000 ₽", "Окупаемость — 4 месяца", "Риски — низкие"]))),
        ("cards", OutlineSlide(id="c", kind=PatternKind.cards, headline=head, content=SlideContent(items=cards))),
        ("table", OutlineSlide(id="t", kind=PatternKind.table, headline=head, content=SlideContent(table=table))),
        ("chart_pair", OutlineSlide(id="cp", kind=PatternKind.chart, headline=head, content=SlideContent(chart=line, chart2=pie, bullets=["Витрина окупится за 4 месяца", "Лояльность удержит гостей"]), takeaway="Прирост выручки — 238 500 ₽ в месяц")),
        ("stat_row", OutlineSlide(id="k", kind=PatternKind.stat_row, headline=head, content=SlideContent(numbers=[NumberCallout(value=v, label=l) for v, l in [("900 000 ₽", "выручка в месяц"), ("13,3%", "операционная прибыль"), ("238 500 ₽", "прирост"), ("4 мес.", "окупаемость")]]))),
    ]


@pytest.mark.parametrize("env_name", ["sparse_env", "big_env"])
@pytest.mark.parametrize("strategy", ["structured", "visual", "compact"])
def test_dense_blocks_stay_on_the_slide(env_name, strategy, request):
    env = request.getfixturevalue(env_name)
    deck, manifest, ws = env
    W, H = (LO_W, LO_H) if env_name == "sparse_env" else (BIG_W, BIG_H)
    for comp, o in _dense_slides():
        _, [(slide, warnings)] = _render(env, [o], comp, strategy)
        for el, (x, y, w, h) in _boxes(slide):
            assert x >= -1 and y >= -1 and x + w <= W + 0.005 * W and y + h <= H + 0.005 * H, (comp, strategy, el.find(".//" + q("p:cNvPr")).get("name"), (x / W, y / H, w / W, h / H))
        assert not any("clamped" in m for m in warnings), (comp, strategy, warnings)


def test_pie_legend_stays_inside_its_box(sparse_env):
    _, slides = _render(sparse_env, [o for c, o in _dense_slides() if c == "chart_pair"], "chart_pair", "compact")
    slide, warnings = slides[0]
    legend = [(el, b) for el, b in _boxes(slide) if (el.find(".//" + q("p:cNvPr")).get("name") or "").startswith(("Legend", "Share", "Swatch"))]
    assert legend
    assert max(b[0] + b[2] for _, b in legend) <= LO_W
    assert max(b[1] + b[3] for _, b in legend) <= LO_H


# ---------------------------------------------------------------------------------------------- T14 neutral runs


def test_engine_runs_do_not_inherit_caps_or_tracking(sparse_env):
    for comp, o in _dense_slides():
        _, [(slide, _)] = _render(sparse_env, [o], comp)
        for el, _ in _boxes(slide):
            name = el.find(".//" + q("p:cNvPr")).get("name") or ""
            if el.find(".//" + q("p:ph")) is not None:
                continue  # the heading placeholder keeps the template's own heading look
            for r in el.iter(q("a:rPr")):
                if r.getparent() is not None and etree.QName(r.getparent()).localname == "r":
                    assert r.get("cap") == "none" and r.get("spc") == "0", (comp, name)


# ---------------------------------------------------------------------------------------------- T18 palette


def test_monochrome_template_accents_with_its_own_colours():
    from verstka.rendering.compose import palette_accents
    from verstka.schemas.template import ColorToken, Tokens

    mono = Tokens(colors=[
        ColorToken(hex="000000", role="background.dark", roles=["background.dark"], weight=300.0),
        ColorToken(hex="FFFFFF", role="text.primary", roles=["text.primary"], weight=6.0),
        ColorToken(hex="CCCCCC", role="neutral.1", roles=["neutral.1"], weight=1.0),
        ColorToken(hex="111111", role="surface", roles=["surface"], weight=0.1),
    ])
    acc = palette_accents(mono)
    assert acc and "0077FF" not in acc  # never a colour the template does not use
    assert set(acc) <= {"FFFFFF", "CCCCCC"}  # no ground as an accent
    branded = Tokens(colors=[ColorToken(hex="FFFFFF", role="background.light", roles=["background.light"]), ColorToken(hex="E4572E", role="accent.1", roles=["accent.1"])])
    assert palette_accents(branded) == ["E4572E"]


# ---------------------------------------------------------------------------------------------- T10 chart pairs


def test_two_bar_charts_stay_side_by_side_on_a_4_3_slide(tmp_path):
    deck = build_sparse_deck(tmp_path / "classic.pptx", 9144000, 6858000, title_pt=40, body_pt=24)
    manifest = analyze_template(deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    ws = TemplateWorkspace.open(manifest.template_id, tmp_path / "ws")
    a = ChartSpec(type="column", title="Количество покупок", categories=["Сейчас", "Цель"], series=[InlineSeries(name="Покупки", values=[100, 115])])
    b_ = ChartSpec(type="column", title="Средний чек", categories=["Сейчас", "Цель"], series=[InlineSeries(name="Чек", values=[300, 330])], unit="₽")
    o = OutlineSlide(id="pair", kind=PatternKind.chart, headline="Выручка вырастет на 238 500 ₽", content=SlideContent(chart=a, chart2=b_, bullets=["Комбо с напитками", "Программа лояльности", "Предложения для офисов"]))
    for strategy in ("structured", "visual", "compact"):
        _, [(slide, warnings)] = _render((deck, manifest, ws), [o], "chart_pair", strategy)
        charts = [b for el, b in _boxes(slide) if etree.QName(el).localname == "graphicFrame" and el.find(".//{http://schemas.openxmlformats.org/drawingml/2006/chart}chart") is not None]
        assert len(charts) == 2, strategy
        (x1, y1, w1, h1), (x2, y2, w2, h2) = sorted(charts)
        overlap = min(y1 + h1, y2 + h2) - max(y1, y2)
        assert x2 >= x1 + w1 and overlap >= 0.8 * min(h1, h2), (strategy, charts)  # side by side, never one over the other


# ---------------------------------------------------------------------------------------------- T10 cards restructure


def _words_fit(slide) -> list[str]:
    """Words of engine text boxes wider than their box (the audit's word_break measure, 3 % tolerance)."""
    from verstka.rendering.fonts import text_width_pt

    bad = []
    for el, (x, y, w, h) in _boxes(slide):
        if el.find(".//" + q("p:ph")) is not None or etree.QName(el).localname != "sp":
            continue
        bp = el.find(".//" + q("a:bodyPr"))
        ins = sum(int(bp.get(k) or 91440) for k in ("lIns", "rIns")) if bp is not None else 2 * 91440
        usable = (w - ins) / EMU_PER_PT
        for r in el.iter(q("a:r")):
            rpr = r.find(q("a:rPr"))
            t = r.find(q("a:t"))
            if rpr is None or t is None or not rpr.get("sz"):
                continue
            lat = rpr.find(q("a:latin"))
            size = int(rpr.get("sz")) / 100
            for word in (t.text or "").split(" "):
                if word and text_width_pt(word, lat.get("typeface") if lat is not None else None, size, rpr.get("b") == "1") > usable * 1.03:
                    bad.append(word)
    return bad


def test_cards_too_narrow_for_their_words_take_two_rows(tmp_path):
    deck = build_sparse_deck(tmp_path / "classic.pptx", 9144000, 6858000, title_pt=40, body_pt=24)
    manifest = analyze_template(deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    ws = TemplateWorkspace.open(manifest.template_id, tmp_path / "ws")
    bullets = ["Партнёрства с пятью ближайшими офисами", "Программа лояльности с понятными условиями", "Продвижение в районных сообществах", "Дневные предложения с 15:00 до 18:00", "Рост маркетингового бюджета до 35 000 рублей в месяц"]
    o = OutlineSlide(id="b", kind=PatternKind.bullets, headline="Цель — увеличить число покупок со 100 до 115 в день", content=SlideContent(bullets=bullets))
    _, [(slide, warnings)] = _render((deck, manifest, ws), [o], "bullets", "visual")
    assert not _words_fit(slide), _words_fit(slide)
    texts = [b for el, b in _boxes(slide) if (el.find(".//" + q("p:cNvPr")).get("name") or "").startswith(("Card text", "Item", "Card"))]
    assert texts
    assert len({round(b[1] / 9144) for b in texts}) >= 2  # never five slivers in one row


# ---------------------------------------------------------------------------------------------- T06 art in the area


def _deck_with_corner_art(path: Path) -> tuple[Path, tuple[float, float, float, float]]:
    """A 16:9 template whose content layout draws a tree-sized shape in the lower right corner of the content band."""
    from pptx.enum.shapes import MSO_SHAPE

    path = build_sparse_deck(path, 12192000, 6858000, title_pt=36, body_pt=20)
    prs = Presentation(path)
    layout = prs.slide_layouts[1]
    tmp = prs.slides[1]
    box = (0.80, 0.62, 0.14, 0.26)
    shp = tmp.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int(box[0] * 12192000)), Emu(int(box[1] * 6858000)), Emu(int(box[2] * 12192000)), Emu(int(box[3] * 6858000)))
    shp.fill.solid()
    shp.fill.fore_color.rgb = RGBColor(0x2E, 0x8B, 0x57)
    el = shp._element
    el.getparent().remove(el)
    layout.shapes._spTree.append(el)
    prs.save(path)
    return path, box


def test_content_keeps_clear_of_art_standing_in_its_area(tmp_path):
    deck, art = _deck_with_corner_art(tmp_path / "art.pptx")
    manifest = analyze_template(deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    ws = TemplateWorkspace.open(manifest.template_id, tmp_path / "ws")
    o = [x for c, x in _dense_slides() if c == "stat_row"][0]
    _, [(slide, warnings)] = _render((deck, manifest, ws), [o], "stat_row", "structured")
    W, H = 12192000, 6858000
    ax, ay, aw, ah = art[0] * W, art[1] * H, art[2] * W, art[3] * H
    for el, (x, y, w, h) in _boxes(slide):
        if el.find(".//" + q("p:ph")) is not None:
            continue
        ox = max(0, min(x + w, ax + aw) - max(x, ax))
        oy = max(0, min(y + h, ay + ah) - max(y, ay))
        assert ox * oy <= 0.02 * w * h, (el.find(".//" + q("p:cNvPr")).get("name"), warnings)


# ---------------------------------------------------------------------------------------------- T14 heading look


def test_heading_fill_keeps_the_sample_run_look():
    from verstka.rendering.synth import _fill_keep
    from verstka.rendering.textfill import ParagraphSpec

    xml = (
        '<p:sp xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<p:nvSpPr><p:cNvPr id="2" name="TextBox 1"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr/>'
        '<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" sz="6050"/><a:t>Title Text Demo</a:t></a:r>'
        '<a:endParaRPr lang="ru-RU" sz="10000" cap="none" spc="0" baseline="0"/></a:p></p:txBody></p:sp>'
    )
    el = etree.fromstring(xml)
    _fill_keep(el, [ParagraphSpec("Выручка за 30 дней — 900 000 ₽")], size_pt=60.5)
    runs = [r for r in el.iter(q("a:rPr"))]
    assert runs and all(r.get("cap") == "none" and r.get("spc") == "0" for r in runs)
    assert "Выручка" in "".join(t.text or "" for t in el.iter(q("a:t")))


def test_largest_empty_rectangle_of_a_cell_grid():
    from verstka.rendering.synth import _largest_empty

    n = 8
    busy = [[(i >= 5 and j >= 4) or (i == 0 and j == 0) for i in range(n)] for j in range(n)]
    got = _largest_empty(busy, Bbox(x=0, y=0, w=800, h=800), n)
    # columns 0–4 below the busy corner cell (5 × 7) beat columns 1–4 at full height (4 × 8)
    assert got is not None and (got.x, got.y, got.w, got.h) == (0, 100, 500, 700)


def test_pie_in_a_wide_low_box_keeps_its_legend_beside_the_circle(big_env):
    """A band left over a conclusion (wide, a quarter of the slide high) on a 15″ slide: the legend goes beside the
    circle at a dense size — never a dot of a pie over a legend running out of the box."""
    from verstka.rendering.compose import Composer

    deck, manifest, ws = big_env
    b = DeckBuilder(deck)
    slide = b.add_blank_slide(6)
    kit = Kit(manifest, BIG_W, BIG_H, "FFFFFF")
    pie = [o for c, o in _dense_slides() if c == "chart_pair"][0].content.chart2
    o = OutlineSlide(id="p", kind=PatternKind.chart, headline="Распределение вложений", content=SlideContent(chart=pie))
    comp = Composer(slide, kit, o, DeckOutline(title="T", slides=[o]), "visual", manifest)
    box = Bbox(x=int(0.58 * BIG_W), y=int(0.55 * BIG_H), w=int(0.376 * BIG_W), h=int(0.2 * BIG_H))  # too low for the usual sizes
    n0 = len(comp.cv.tree)
    comp._pie(box, pie, center=False)
    drawn = [(el, element_bbox(el)) for el in list(comp.cv.tree)[n0:] if element_bbox(el)]
    legend = [bb for el, bb in drawn if (el.find(".//" + q("p:cNvPr")).get("name") or "").startswith(("Legend", "Share", "Swatch"))]
    assert legend
    tol = int(0.01 * BIG_H)
    assert max(x + w for x, y, w, h in legend) <= box.x + box.w + tol and max(y + h for x, y, w, h in legend) <= box.y + box.h + tol
    charts = [bb for el, bb in drawn if etree.QName(el).localname == "graphicFrame"]
    assert charts and charts[0][3] >= 0.45 * box.h  # the circle keeps most of the band's height
    assert "pie legend does not fit its box" not in comp.warnings and getattr(comp, "_pie_clean", False)


def test_heading_starts_after_a_mark_standing_over_its_left_part(simple_deck):
    """A big page number «09» kept at the left of the heading's box: the heading's letters start after its ink (not
    after its frame), and nothing moves when the mark stands elsewhere."""
    from verstka.rendering.synth import _left_clear

    b = DeckBuilder(simple_deck)
    slide = b.add_blank_slide(6)
    W, H = b.slide_w, b.slide_h
    tb = slide.shapes.add_textbox(Emu(int(0.037 * W)), Emu(int(0.04 * H)), Emu(int(0.094 * W)), Emu(int(0.08 * H)))
    tb.text_frame.text = "09"
    _style_runs(tb.text_frame, 28, True)
    head = Bbox(x=int(0.05 * W), y=int(0.04 * H), w=int(0.86 * W), h=int(0.08 * H))
    past = _left_clear(slide, head, W, H)
    assert head.x < past < int(0.037 * W) + int(0.094 * W) + int(0.015 * W)  # after the digits' ink, inside their frame
    below = Bbox(x=int(0.05 * W), y=int(0.3 * H), w=int(0.86 * W), h=int(0.08 * H))
    assert _left_clear(slide, below, W, H) == below.x  # the mark is not in this band


# ---------------------------------------------------------------------------------------------- gate 1 (writer decks)


def _picture(path: Path, photo: bool) -> Path:
    """A photograph-like picture (fine multi-coloured texture, opaque) or a flat illustration (a few solid shapes)."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    if photo:
        rng = np.random.default_rng(7)
        base = rng.integers(0, 256, size=(300, 400, 3), dtype=np.uint8)
        im = Image.fromarray(base).filter(ImageFilter.GaussianBlur(1.2))
    else:
        im = Image.new("RGB", (400, 300), (255, 255, 255))
        d = ImageDraw.Draw(im)
        d.ellipse((20, 20, 180, 180), fill=(0, 119, 255))
        d.rectangle((200, 60, 380, 260), fill=(255, 51, 153))
    im.save(path)
    return path


def _deck_with_side_picture(path: Path, pic: Path) -> Path:
    """A cover and two text slides whose layout draws a picture over its right half (the art every slide of that
    layout carries, as VK Education's «Паттерн + фото»); the title and the text at the left."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    W, H = prs.slide_width, prs.slide_height
    cover = prs.slides.add_slide(prs.slide_layouts[0])
    cover.shapes.title.text = "Обложка"
    layout = prs.slide_layouts[1]
    for ph, (y, h) in zip(layout.placeholders, [(0.08, 0.15), (0.3, 0.55)]):
        ph.left, ph.top, ph.width, ph.height = Emu(int(0.06 * W)), Emu(int(y * H)), Emu(int(0.4 * W)), Emu(int(h * H))
    # the picture goes onto the layout, with its image part
    from pptx.oxml.shapes.picture import CT_Picture

    _part, rid = layout.part.get_or_add_image_part(str(pic))
    layout.shapes._spTree.append(CT_Picture.new_pic(90, "Art 90", "", rid, int(0.52 * W), 0, int(0.48 * W), H))
    for n in range(2):
        s = prs.slides.add_slide(layout)
        s.shapes.title.text = f"Заголовок слайда {n + 1}"
        s.placeholders[1].text = "Первый пункт слайда"
        s.placeholders[1].text_frame.add_paragraph().text = "Второй пункт слайда"
    prs.save(path)
    return path


@pytest.mark.parametrize("photo", [True, False])
def test_photo_art_never_frames_a_text_slide(tmp_path, photo):
    """G1-04: a template's sample photo (a smiling student with a laptop) is its own story — a composed text slide is
    not set beside it; a flat brand illustration stays art."""
    from verstka.rendering.synth import _choose_art, _find_art, _is_photo

    deck = _deck_with_side_picture(tmp_path / "art.pptx", _picture(tmp_path / "pic.png", photo))
    manifest = analyze_template(deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    b = DeckBuilder(deck)
    arts = [a for a in (_find_art(b, p, manifest) for p in manifest.patterns) if a is not None]
    assert arts, "the side picture is art of the template"
    assert all(a.photo is photo for a in arts)
    lay = b.source_slide(2).slide_layout.part
    pics = [r.target_part for r in lay.rels.values() if not r.is_external and r.reltype.endswith("/image")]
    assert pics and _is_photo(b, pics[0]) is photo
    o = OutlineSlide(id="s1", kind=PatternKind.bullets, headline="Япония атаковала Перл-Харбор", content=SlideContent(bullets=["7 декабря 1941 года — атака", "США вступили в войну"]))
    outline = DeckOutline(title="T", strategy="visual", slides=[o])
    ds = deck_style(b, manifest, outline)
    got = _choose_art(b, manifest, ds, "bullets", o, outline)
    assert (got is None) if photo else (got is not None)


def test_figure_split_keeps_short_units_with_the_number():
    from verstka.rendering.compose import figure_split

    assert figure_split("27 миллионов человек") == ("27", "миллионов человек")
    assert figure_split("40 стран") == ("40", "стран")
    assert figure_split("12 млн ₽ выручки") == ("12 млн ₽", "выручки")
    for v in ("300 ₽", "−69%", "1 854", "4,6 из 5", "31% → 12%", "в 2 раза"):
        assert figure_split(v) is None


@pytest.mark.parametrize("strategy", ["structured", "visual", "compact"])
def test_worded_stat_values_keep_a_figure_size_over_their_labels(simple_deck, tmp_path, strategy):
    """G1-14: «27 миллионов человек / Потери СССР» — the number is set at a figure's size (never below its label), the
    words it counts on the line under it, in the same text (the value stays whole for the audit)."""
    manifest = analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    ws = TemplateWorkspace.open(manifest.template_id, tmp_path / "ws")
    nums = [NumberCallout(value="27 миллионов человек", label="Потери СССР"), NumberCallout(value="40 стран", label="Территории"), NumberCallout(value="61 государство", label="Участники")]
    o = OutlineSlide(id="s9", kind=PatternKind.stat_row, headline="СССР потерял 27 миллионов человек", content=SlideContent(numbers=nums, bullets=["Китай, Германия, Япония и Польша также понесли большие потери"]))
    _, out = _render((simple_deck, manifest, ws), [o], "stat_row", strategy)
    slide = out[0][0]
    figs, labels = [], []
    for el, _b in _boxes(slide):
        name = el.find(".//" + q("p:cNvPr")).get("name") or ""
        sizes = [int(r.get("sz")) / 100 for r in el.iter(q("a:rPr")) if r.get("sz")]
        text = "".join(t.text or "" for t in el.iter(q("a:t")))
        if name.startswith("Figure"):
            figs.append((sizes, text))
        elif name.startswith("Label"):
            labels.append(max(sizes))
    assert len(figs) == 3 and labels
    for sizes, text in figs:
        assert sizes[0] >= 1.5 * max(labels)  # the number is the hero of its tile
        assert min(sizes) >= max(labels) - 0.05  # its words never smaller than the label
    whole = ["".join(t.split()).replace("⁠", "") for _, t in figs]
    assert "27миллионовчеловек" in whole and "61государство" in whole


def test_a_year_is_never_the_hero_figure_of_a_conclusion():
    """G1-15: «Это меньше, чем в первом квартале 2024 года» has no key figure; a count stays one."""
    from verstka.rendering.compose import _aside_figure

    assert _aside_figure("Это меньше, чем в первом квартале 2024 года") is None
    assert _aside_figure("С 2019 по 2024 число выросло вдвое") is None
    assert _aside_figure("В 2025 году продано 1854 электромобиля") == "1854"
    assert _aside_figure("Продажи выросли на 12% к 2024") == "12%"


def test_pie_of_amounts_keeps_the_amounts_beside_a_smaller_circle(sparse_env):
    """G1-21: the legend of a pie of the brief's amounts keeps «315 000 ₽ · 40%» while the circle keeps over a third of
    its box's height — not the shares alone next to a larger circle."""
    from verstka.rendering.compose import Composer

    deck, manifest, ws = sparse_env
    b = DeckBuilder(deck)
    slide = b.add_blank_slide(6)
    kit = Kit(manifest, LO_W, LO_H, "FFFFFF")
    cats = ["Продукты, упаковка и списания", "Зарплаты и связанные начисления", "Аренда", "Коммунальные услуги", "Маркетинг", "Другие операционные расходы"]
    pie = ChartSpec(type="pie", title=None, categories=cats, series=[InlineSeries(name="Расходы", values=[315000, 270000, 120000, 25000, 20000, 30000])], unit="₽")
    o = OutlineSlide(id="p", kind=PatternKind.chart, headline="Структура расходов", content=SlideContent(chart=pie))
    comp = Composer(slide, kit, o, DeckOutline(title="T", slides=[o]), "compact", manifest)
    box = Bbox(x=int(0.4 * LO_W), y=int(0.25 * LO_H), w=int(0.4 * LO_W), h=int(0.4 * LO_H))
    n0 = len(comp.cv.tree)
    comp._pie(box, pie, center=False)
    drawn = [(el.find(".//" + q("p:cNvPr")).get("name") or "", "".join(t.text or "" for t in el.iter(q("a:t"))), element_bbox(el)) for el in list(comp.cv.tree)[n0:]]
    shares = [t for name, t, _ in drawn if name.startswith("Share")]
    assert len(shares) == 6 and all("₽" in t for t in shares)
    circle = [bb for name, _, bb in drawn if name.startswith("Chart") or bb and bb[2] == bb[3]]
    tol = int(0.01 * LO_H)
    assert all(bb[0] + bb[2] <= box.x + box.w + tol and bb[1] + bb[3] <= box.y + box.h + tol for _, _, bb in drawn if bb)
    assert circle and circle[0][3] >= Composer.PIE_KEEP_AMOUNTS * box.h - tol


def test_a_long_table_is_set_narrower_than_a_wall_over_the_slide(sparse_env, monkeypatch):
    """G1-21 / VK Tech long: an 8-row table under its heading, with a conclusion, does not cover more than 80 % of the
    safe area (the audit's fill_ratio): its rows stop growing, then it is set as wide as its columns need — at the
    same type size, at last a step smaller."""
    from verstka.rendering.compose import Composer

    rows = [["Покупки в день", "100", "115"], ["Средний чек", "300 рублей", "330 рублей"], ["Месячная выручка", "900 000 рублей", "1 138 500 рублей"], ["Переменные расходы", "315 000 рублей", "375 705 рублей"], ["Постоянные операционные расходы", "465 000 рублей", "508 000 рублей"], ["Операционная прибыль", "120 000 рублей", "254 795 рублей"], ["Операционная рентабельность", "13,3%", "22,4%"], ["Точка безубыточности", "62 покупки", "58 покупок"]]
    t = TableData(columns=["Показатель", "Сейчас", "Цель"], rows=rows)
    o = OutlineSlide(id="t", kind=PatternKind.table, headline="Операционная прибыль вырастет в 2,1 раза", takeaway="Выручка увеличивается на 26,5%, а ежемесячная операционная прибыль — примерно на 112%", content=SlideContent(table=t))
    deck, manifest, ws = sparse_env
    # a template whose safe area stops higher (a band of chrome at the foot): the table's room is the wall's size
    safe = manifest.tokens.spacing.safe_area.model_copy(update={"h": 0.8})
    tokens = manifest.tokens.model_copy(update={"spacing": manifest.tokens.spacing.model_copy(update={"safe_area": safe})})
    manifest = manifest.model_copy(update={"tokens": tokens})

    def compose():
        b = DeckBuilder(deck)
        slide = b.add_blank_slide(6)
        sx, sy, sw, sh = int(safe.x * LO_W), int(safe.y * LO_H), int(safe.w * LO_W), int(safe.h * LO_H)
        slide.shapes.add_textbox(Emu(sx), Emu(sy), Emu(sw), Emu(int(0.08 * LO_H))).text_frame.text = o.headline
        comp = Composer(slide, Kit(manifest, LO_W, LO_H, "FFFFFF"), o, DeckOutline(title="T", slides=[o], strategy="structured"), "structured", manifest)
        area = Bbox(x=sx, y=sy + int(0.1 * LO_H), w=sw, h=sh - int(0.1 * LO_H))
        n0 = len(comp.cv.tree)
        comp.compose("table", area)
        comp._notes = None  # the conclusion is drawn now: measured as a block of the slide
        frame = next(el for el, _ in _boxes(slide) if etree.QName(el).localname == "graphicFrame")
        sizes = {int(r.get("sz")) for r in frame.iter(q("a:rPr")) if r.get("sz")}
        return comp._coverage(n0, area), sizes

    with monkeypatch.context() as m:
        m.setattr(Composer, "FILL_MAX", 5.0)
        wall, sizes0 = compose()
    assert wall > 0.8  # the case: grown rows at the full width cover more than the audit allows
    got, sizes = compose()
    assert got <= Composer.FILL_MAX <= 0.8
    assert min(sizes) >= min(sizes0) * 0.75  # a step smaller at most

