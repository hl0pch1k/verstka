"""Agent v2 content on the page: inline chart data, two charts side by side, a formula set large, a pie with its own
legend, the target column of a table, the slide's conclusion and footnote, a cover's small print.

Synthetic decks only (the conftest deck and a hand-drawn cover): the rules hold for any template."""

from __future__ import annotations

import re

from pathlib import Path

import pytest
from lxml import etree
from pptx import Presentation
from pptx.util import Emu, Pt

from verstka.analysis.manifest import analyze_template
from verstka.analysis.xmlns import q
from verstka.ingest.workspace import TemplateWorkspace
from verstka.matching.compat import composition_for
from verstka.rendering.charts import chart_data_ok, delta_e, pie_palette, pie_shades, resolve_series
from verstka.rendering.clone import render_clone
from verstka.rendering.compose import parse_formula
from verstka.rendering.deck import DeckBuilder, element_bbox
from verstka.rendering.fallbacks import prepare_slide
from verstka.rendering.synth import render_synth
from verstka.rendering.tables import emphasis_column
from verstka.schemas.common import BboxFrac, Family, PatternKind, SlotRole
from verstka.schemas.layout import LayoutSlide
from verstka.schemas.outline import ChartSpec, DeckOutline, InlineSeries, NumberCallout, OutlineSlide, Series, SlideContent, SlideItem, TableData
from verstka.schemas.template import Capacity, FontUsage, Pattern, SlideSize, Slot, SlotStyle, Spacing, TemplateManifest, Tokens, TypeStep, Typography

W, H = 12192000, 6858000
C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"

PIE = ChartSpec(type="pie", title="Структура выручки", unit="₽", categories=["Кофе", "Десерты и выпечка", "Чай и другие напитки"], series=[InlineSeries(name="Выручка", values=[540000, 225000, 135000])])
EXPENSES = ChartSpec(
    type="doughnut", title="Расходы за месяц", unit="₽",
    categories=["Продукты и упаковка", "Зарплаты", "Аренда", "Коммунальные услуги", "Маркетинг", "Прочие расходы"],
    series=[InlineSeries(name="Расходы", values=[315000, 270000, 120000, 25000, 20000, 30000])],
)
BUYS = ChartSpec(type="column", title="Покупок в день", categories=["Сейчас", "Через 6 месяцев"], series=[InlineSeries(name="Покупки", values=[100, 115])], highlight_index=1)
CHECK = ChartSpec(type="column", title="Средний чек", unit="₽", categories=["Сейчас", "Через 6 месяцев"], series=[InlineSeries(name="Чек", values=[300, 330])], highlight_index=1)
REVENUE = ChartSpec(
    type="line", title="Прогноз выручки", unit="тыс. ₽",
    categories=["Сейчас", "1-й", "2-й", "3-й", "4-й", "5-й", "6-й"], series=[InlineSeries(name="Выручка", values=[900, 930, 970, 1015, 1060, 1100, 1138.5])],
)
TARGETS = TableData(columns=["Показатель", "Сейчас", "Цель"], rows=[["Покупки в день", "100", "115"], ["Средний чек", "300 ₽", "330 ₽"], ["Операционная прибыль", "120 000 ₽", "254 795 ₽"]])


# ---------------------------------------------------------------------------------------------- data and decisions


def test_inline_chart_data_is_drawn_when_the_ids_name_nothing():
    deck = DeckOutline(title="T", series=[Series(id="s1", name="Другое", categories=["a", "b"], values=[1, 2])])
    got = resolve_series(PIE, deck)
    assert [s.name for s in got] == ["Выручка"] and got[0].categories == PIE.categories and got[0].values == [540000, 225000, 135000]
    assert got[0].unit == "₽"
    # registry ids win over the inline copy; ids that name nothing fall back to the inline data, not to s1
    assert resolve_series(PIE.model_copy(update={"series_ids": ["s1"]}), deck)[0].id == "s1"
    assert resolve_series(PIE.model_copy(update={"series_ids": ["typo"]}), deck)[0].name == "Выручка"
    assert chart_data_ok(PIE, deck) and chart_data_ok(PIE, DeckOutline(title="T"))
    # a short series leaves a gap at its end, several series stay several
    short = ChartSpec(type="line", categories=["a", "b", "c"], series=[InlineSeries(name="x", values=[1, 2]), InlineSeries(name="y", values=[3, 4, 5])])
    s = resolve_series(short, DeckOutline(title="T"))
    assert [x.name for x in s] == ["x", "y"] and list(s[0].values) == [1, 2, None]
    # a chart without any data of its own still has none
    assert not chart_data_ok(ChartSpec(type="pie", categories=["a", "b"]), DeckOutline(title="T"))


def test_compositions_for_agent_content():
    pair = OutlineSlide(id="p", kind=PatternKind.chart, headline="Два графика", content=SlideContent(chart=BUYS, chart2=CHECK))
    assert composition_for(pair) == "chart_pair"
    formula = OutlineSlide(id="f", kind=PatternKind.big_number, headline="Выручка", content=SlideContent(formula="100 × 300 × 30 = 900 000 рублей"))
    assert composition_for(formula) == "formula"
    with_chart = OutlineSlide(id="fc", kind=PatternKind.chart, headline="x", content=SlideContent(chart=PIE, formula="1 + 2 = 3"))
    assert composition_for(with_chart) == "chart_text"
    with_cards = OutlineSlide(id="fk", kind=PatternKind.cards, headline="x", content=SlideContent(items=[SlideItem(title="a", text="b"), SlideItem(title="c", text="d")], formula="1 + 2 = 3"))
    assert composition_for(with_cards) == "cards"
    cover = OutlineSlide(id="t", kind=PatternKind.title, headline="x", content=SlideContent(formula="1 + 2 = 3"))
    assert composition_for(cover) == "title"


def test_formula_terms_and_operators():
    terms, ops = parse_formula("100 покупок × 300 ₽ × 30 дней = 900 000 рублей")
    assert terms == [("100", "покупок"), ("300 ₽", ""), ("30", "дней"), ("900 000 ₽", "")]
    assert ops == ["×", "×", "="]
    terms, ops = parse_formula("Выручка = 100 * 300 * 30")
    assert terms[0] == (None, "Выручка") and ops == ["=", "×", "×"]
    terms, ops = parse_formula("1 138 500 − 900 000 = 238 500 ₽")
    assert [t[0] for t in terms] == ["1 138 500", "900 000", "238 500 ₽"] and ops == ["−", "="]


def test_the_target_column_of_a_comparison_table():
    assert emphasis_column(TARGETS) == 2
    assert emphasis_column(TableData(columns=["Метрика", "2024", "2025"], rows=[["a", "1", "2"]])) == 2
    assert emphasis_column(TableData(columns=["Показатель", "Было", "Стало", "Изменение"], rows=[["a", "1", "2", "+1"]])) == 2
    assert emphasis_column(TableData(columns=["Тариф", "Цена", "Пользователи"], rows=[["a", "1", "2"]])) is None  # options: no answer column
    assert emphasis_column(TableData(columns=["a", "b"], rows=[["1", "2"]])) is None


def test_pie_largest_slice_in_the_accent_others_in_its_tints():
    vals = [30, 60, 10]
    shades = pie_shades(vals, "0077FF", "FFFFFF")
    assert shades[1] == ("0077FF", 1.0)  # the largest slice, wherever it stands
    assert all(base == "0077FF" for base, _ in shades) and shades[0][1] > shades[2][1]  # the bigger the part, the stronger
    pal = pie_palette(vals, "0077FF", "FFFFFF")
    assert delta_e(pal[1], pal[0]) >= 20 and delta_e(pal[0], pal[2]) >= 20
    # a remainder is quiet (no hue), and every tint stays visible on a dark ground as well
    six = [315, 270, 120, 25, 20, 30]
    dark = pie_palette(six, "0077FF", "000000", quiet_idx=[5])
    from verstka.schemas.common import contrast_ratio

    assert all(contrast_ratio(c, "000000") >= 1.55 for c in dark)
    assert len(set(dark)) == 6


def test_second_chart_without_data_is_dropped_and_a_lone_second_chart_becomes_the_chart():
    outline = DeckOutline(title="T")
    empty = ChartSpec(type="column", series_ids=["nothing"])
    s = OutlineSlide(id="p", kind=PatternKind.chart, headline="x", content=SlideContent(chart=BUYS, chart2=empty))
    got, ps, notes = prepare_slide(s, LayoutSlide(outline_id="p", mode="synth", composition="chart_pair"), outline)
    assert got.content.chart2 is None and ps.composition == "chart_text" and any("second chart" in n for n in notes)
    s = OutlineSlide(id="q", kind=PatternKind.chart, headline="x", content=SlideContent(chart=None, chart2=CHECK))
    got, ps, _ = prepare_slide(s, LayoutSlide(outline_id="q", mode="synth", composition="chart_text"), outline)
    assert got.content.chart is not None and got.content.chart.title == "Средний чек" and got.content.chart2 is None
    # a figure slide carrying a formula is not a figure slide without figures
    f = OutlineSlide(id="f", kind=PatternKind.big_number, headline="x", content=SlideContent(formula="100 × 300 × 30 = 900 000 ₽"), takeaway="Вывод", footnote="Сноска")
    got, ps, notes = prepare_slide(f, LayoutSlide(outline_id="f", mode="synth", composition="formula"), outline)
    assert got is f and not notes


# ---------------------------------------------------------------------------------------------- on the page


@pytest.fixture
def env(simple_deck, tmp_path):
    manifest = analyze_template(simple_deck, workspace_root=tmp_path / "ws", use_llm=False, use_vlm=False, render=False)
    ws = TemplateWorkspace.open(manifest.template_id, tmp_path / "ws")
    return simple_deck, manifest, ws


def _render(env, oslide: OutlineSlide, strategy: str = "structured"):
    deck, manifest, ws = env
    b = DeckBuilder(deck)
    outline = DeckOutline(title="T", strategy=strategy, slides=[oslide])
    oslide, ps, _ = prepare_slide(oslide, LayoutSlide(outline_id=oslide.id, mode="synth", composition=composition_for(oslide)), outline)
    slide, warnings = render_synth(b, ps, oslide, manifest, ws, outline)
    return slide, warnings, manifest


def _named(slide, prefix: str):
    return [sh for sh in slide.shapes if sh.name.startswith(prefix)]


def _one(slide, name: str):
    """The shapes named exactly «name N» (not «name strip N»)."""
    return [sh for sh in slide.shapes if sh.name.rsplit(" ", 1)[0] == name]


def _text(sh) -> str:
    return sh.text_frame.text.replace("\u00a0", " ").replace("\u2060", "")


def _box(sh):
    return sh.left, sh.top, sh.left + sh.width, sh.top + sh.height


def _overlap(a, b) -> bool:
    ax0, ay0, ax1, ay1 = _box(a)
    bx0, by0, bx1, by1 = _box(b)
    return min(ax1, bx1) - max(ax0, bx0) > 0 and min(ay1, by1) - max(ay0, by0) > 0


def test_conclusion_and_footnote_under_a_chart(env):
    s = OutlineSlide(id="c", kind=PatternKind.chart, headline="Выручка растет каждый месяц", content=SlideContent(chart=REVENUE),
                     takeaway="За полгода выручка вырастет на 238 500 ₽ в месяц", footnote="Это предполагаемая траектория роста, а не гарантированный результат")
    slide, warnings, manifest = _render(env, s)
    assert not [w for w in warnings if "fail" in w], warnings
    chart = next(sh for sh in slide.shapes if sh.has_chart)
    take, foot = _one(slide, "Conclusion")[0], _named(slide, "Footnote")[0]
    bar = _named(slide, "Conclusion bar")[0]
    assert "238" in take.text_frame.text and foot.text_frame.text.startswith("Это предполагаемая")
    # one line for the conclusion, the footnote smaller than it, in that order down the page, clear of each other
    t_sizes = {r.font.size.pt for p in take.text_frame.paragraphs for r in p.runs}
    f_sizes = {r.font.size.pt for p in foot.text_frame.paragraphs for r in p.runs}
    assert max(f_sizes) < min(t_sizes) and max(f_sizes) >= 8
    assert chart.top + chart.height <= take.top and take.top + take.height <= foot.top
    assert bar.left < take.left and bar.top >= take.top - Emu(Pt(4)) and bar.top + bar.height <= take.top + take.height + Emu(Pt(4))
    # the figures of the conclusion in the accent
    runs = [r for p in take.text_frame.paragraphs for r in p.runs]
    assert len({str(r.font.color.rgb) for r in runs}) >= 2
    # never over the footer of the template (the conftest deck's «ACME» at 92% of the height)
    assert foot.top + foot.height <= int(0.92 * H)
    # the chart draws the inline data: the last point labelled in the accent
    cs = chart.chart._chartSpace
    vals = [float(v.text) for v in cs.find(f".//{C}ser/{C}val").iter(f"{C}v")]
    assert vals[-1] == 1138.5
    last = [d for d in cs.iter(f"{C}dLbl") if d.find(f"{C}idx").get("val") == str(len(vals) - 1)]
    assert last and last[0].find(f"{C}delete") is None


def test_conclusion_follows_short_content_and_stays_one_line(env):
    items = [SlideItem(title="Больше покупок", text="Со 100 до 115 в день"), SlideItem(title="Выше чек", text="С 300 до 330 ₽"), SlideItem(title="Меньше потерь", text="С 35% до 33%")]
    s = OutlineSlide(id="k", kind=PatternKind.cards, headline="Три изменения", content=SlideContent(items=items), takeaway="Каждую неделю проверяем покупки, чек и потери")
    slide, _, _ = _render(env, s)
    take = _one(slide, "Conclusion")[0]
    cards = [sh for sh in slide.shapes if sh.name.startswith("Card ") and not sh.has_text_frame or (sh.name.startswith("Card ") and not sh.text_frame.text.strip())]
    bottom = max(c.top + c.height for c in cards)
    assert 0 < take.top - bottom <= int(0.08 * H), "the conclusion follows the cards, not the foot of the slide"
    assert take.height <= Emu(Pt(max(r.font.size.pt for p in take.text_frame.paragraphs for r in p.runs) * 1.6))


def test_two_charts_side_by_side_under_their_own_titles(env):
    s = OutlineSlide(id="p", kind=PatternKind.chart, headline="Больше покупок и выше чек", content=SlideContent(chart=BUYS, chart2=CHECK), takeaway="Выручка вырастет до 1 138 500 ₽ в месяц")
    slide, warnings, _ = _render(env, s)
    charts = sorted((sh for sh in slide.shapes if sh.has_chart), key=lambda sh: sh.left)
    titles = sorted(_named(slide, "Chart title"), key=lambda sh: sh.left)
    assert len(charts) == 2 and [t.text_frame.text.replace(" ", " ") for t in titles] == ["Покупок в день", "Средний чек"]
    a, b = charts
    assert a.left + a.width < b.left and abs(a.width - b.width) <= 2 and a.top == b.top
    for t, ch in zip(titles, charts):
        assert t.left == ch.left and t.top + t.height <= ch.top
    # two categories stay columns (a label of a few words wraps under a wide column), the later one highlighted
    for ch in charts:
        assert ch.chart._chartSpace.find(f".//{C}barDir").get("val") == "col"
    assert not _overlap(_one(slide, "Conclusion")[0], a)


def test_formula_set_large_with_the_result_on_an_accent_panel(env):
    s = OutlineSlide(id="f", kind=PatternKind.big_number, headline="Выручка за месяц — 900 000 ₽", content=SlideContent(formula="100 покупок × 300 ₽ × 30 дней = 900 000 рублей"), takeaway="Рост любого множителя увеличивает выручку")
    slide, warnings, _ = _render(env, s)
    figs = _named(slide, "Figure") + _named(slide, "Result figure")
    ops = _named(slide, "Operator")
    labels = [sh.text_frame.text for sh in _named(slide, "Term label")]
    assert len(figs) == 4 and [o.text_frame.text for o in ops] == ["×", "×", "="]
    assert labels == ["покупок", "дней"]
    result = _named(slide, "Result figure")[0]
    assert "900" in result.text_frame.text and "₽" in result.text_frame.text
    panel = _named(slide, "Result")[0]
    assert panel.left <= result.left and panel.left + panel.width >= result.left + Emu(Pt(40))
    # one row, left to right, one figure size; the operators smaller and quieter than the figures
    tops = {sh.top for sh in figs}
    assert len(tops) == 1
    lefts = [sh.left for sh in sorted(figs + ops, key=lambda sh: sh.left)]
    assert lefts == sorted(lefts)
    fig_size = max(r.font.size.pt for r in figs[0].text_frame.paragraphs[0].runs)
    op_size = ops[0].text_frame.paragraphs[0].runs[0].font.size.pt
    assert fig_size >= 40 and op_size < 0.8 * fig_size
    assert str(ops[0].text_frame.paragraphs[0].runs[0].font.color.rgb) != str(figs[0].text_frame.paragraphs[0].runs[0].font.color.rgb)
    # labels under their figures, never over them
    for lab in _named(slide, "Term label"):
        assert not any(_overlap(lab, f) for f in figs)
    right = max(sh.left + sh.width for sh in figs + ops + [panel])
    assert right <= W


def test_pie_with_shares_on_slices_and_a_legend_of_its_own(env):
    s = OutlineSlide(id="d", kind=PatternKind.chart, headline="Две трети расходов — продукты и зарплаты", content=SlideContent(chart=EXPENSES), takeaway="Прибыль — 120 000 ₽, или 13,3% выручки", footnote="Налоги в расчет не включены")
    slide, warnings, manifest = _render(env, s)
    chart = next(sh for sh in slide.shapes if sh.has_chart)
    cs = chart.chart._chartSpace
    assert cs.find(f".//{C}legend") is None  # the legend is set as text beside the circle
    # money values: the chart keeps the brief's amounts (no computed share is written on a slice), the legend gives
    # each part's amount and its share of the total, headed as such
    vals = [float(v.text) for v in cs.find(f".//{C}ser/{C}val").iter(f"{C}v")]
    assert max(vals) == 315000 and abs(sum(vals) - 780000) < 1
    # the slices that have room say the brief's amounts, never a computed share
    fmts = [n.get("formatCode") for n in cs.iter(f"{C}numFmt")]
    assert fmts and not any("%" in (f or "") for f in fmts), fmts
    names = [sh.text_frame.text.replace(" ", " ") for sh in _named(slide, "Legend") if not sh.name.startswith("Legend title")]
    pcts = [re.sub(r"[\s\u00a0\u2060]+", " ", sh.text_frame.text) for sh in _named(slide, "Share")]
    assert names == EXPENSES.categories and [x.split(" · ")[-1] for x in pcts[:3]] == ["40%", "35%", "15%"]
    assert pcts[0].startswith("315 000 ₽")
    swatches = _named(slide, "Swatch")
    assert len(swatches) == 6
    # every swatch is the accent laid over the ground at the slice's share (a colour of the template), the largest opaque
    fills = [sw._element.find(".//" + q("a:srgbClr")) for sw in swatches]
    assert len({f.get("val") for f in fills[:5]}) == 1
    assert fills[0].find(q("a:alpha")) is None and fills[1].find(q("a:alpha")) is not None
    pts = cs.findall(f".//{C}dPt")
    assert pts[0].find(f".//{q('a:srgbClr')}").get("val") == fills[0].get("val")
    # legend rows beside the circle, the caption heads the legend
    head = _named(slide, "Legend title")
    assert head and _text(head[0]).startswith("Расходы за месяц")
    assert all(sw.left >= chart.left + chart.width for sw in swatches)
    take = _one(slide, "Conclusion")[0]
    assert chart.top + chart.height <= take.top


def test_table_target_column_is_tinted(env):
    s = OutlineSlide(id="t", kind=PatternKind.table, headline="К шестому месяцу прибыль вырастет на 112%", content=SlideContent(table=TARGETS), takeaway="Прибыль растет примерно на 112%")
    slide, _, _ = _render(env, s)
    tbl = next(sh for sh in slide.shapes if sh.has_table).table

    def fill(cell):
        sf = cell._tc.tcPr.find(q("a:solidFill")) if cell._tc.tcPr is not None else None
        return None if sf is None else sf[0].get("val")

    def color(cell):
        return str(cell.text_frame.paragraphs[0].runs[0].font.color.rgb)

    for r in range(1, len(TARGETS.rows) + 1):
        assert fill(tbl.cell(r, 2)) is not None and fill(tbl.cell(r, 2)) != fill(tbl.cell(r, 1))
        assert color(tbl.cell(r, 2)) != color(tbl.cell(r, 1))


def test_formula_over_a_chart_is_a_line_with_figures_in_the_accent(env):
    s = OutlineSlide(id="x", kind=PatternKind.chart, headline="Кофе приносит 60% выручки", content=SlideContent(chart=PIE, formula="540 000 + 225 000 + 135 000 = 900 000 ₽"))
    slide, _, _ = _render(env, s)
    intro = _named(slide, "Intro")
    assert intro and "900" in intro[0].text_frame.text
    colors = {str(r.font.color.rgb) for p in intro[0].text_frame.paragraphs for r in p.runs}
    assert len(colors) >= 2


# ---------------------------------------------------------------------------------------------- the cover's small print


def _cover(tmp: Path):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W), Emu(H)
    s = prs.slides.add_slide(prs.slide_layouts[6])
    t = s.shapes.add_textbox(Emu(int(0.06 * W)), Emu(int(0.32 * H)), Emu(int(0.55 * W)), Emu(int(0.16 * H)))
    t.text_frame.word_wrap = True
    r = t.text_frame.paragraphs[0].add_run()
    r.text, r.font.size, r.font.name = "Название", Pt(48), "Play"
    pptx = tmp / "cover.pptx"
    prs.save(pptx)
    typo = Typography(
        families=[FontUsage(family="Play", weight=1.0)],
        scale=[TypeStep(role="display", size_pt=54), TypeStep(role="h1", size_pt=24), TypeStep(role="h2", size_pt=16), TypeStep(role="body", size_pt=12), TypeStep(role="caption", size_pt=10)],
        sizes_used=[54, 48, 36, 24, 20, 16, 14, 12, 10],
    )
    slot = Slot(id="title_t", role=SlotRole.title, shape_id=str(t.shape_id), bbox=BboxFrac(x=0.06, y=0.32, w=0.55, h=0.16), style=SlotStyle(font_family="Play", size_pt=48), capacity=Capacity(max_chars=20, max_lines=1), sample_text="Название")
    p = Pattern(id="pc", source_slide=1, kind=PatternKind.title, family=Family.light, slots=[slot])
    m = TemplateManifest(template_id="synthetic", source_file="s.pptx", slide_size=SlideSize(w=W, h=H), tokens=Tokens(typography=typo, spacing=Spacing(safe_area=BboxFrac(x=0.04, y=0.06, w=0.92, h=0.86))), patterns=[p], n_slides=1)
    return pptx, p, m


def test_cover_carries_the_disclaimer_small_under_the_date(tmp_path):
    pptx, p, m = _cover(tmp_path)
    o = OutlineSlide(id="t", kind=PatternKind.title, headline="Больше прибыли с каждой чашки", subtitle="План развития кофейни на 6 месяцев", footnote="Учебный кейс. Все цифры и прогнозы условные")
    ws = TemplateWorkspace.create(pptx, tmp_path / "ws")
    slide, warnings = render_clone(DeckBuilder(pptx), LayoutSlide(outline_id="t", mode="clone", pattern_id="pc"), o, p, m, ws, DeckOutline(title="x", slides=[o]))
    by_name = {sh.name.split(" ")[0]: sh for sh in slide.shapes}
    note = next(sh for sh in slide.shapes if "условные" in sh.text_frame.text)
    date = next((sh for sh in slide.shapes if sh.name.startswith("Дата")), None)
    heading = next(sh for sh in slide.shapes if "прибыли" in sh.text_frame.text)
    n_size = max(r.font.size.pt for p_ in note.text_frame.paragraphs for r in p_.runs)
    h_size = max(r.font.size.pt for p_ in heading.text_frame.paragraphs for r in p_.runs)
    assert n_size < 0.4 * h_size and n_size >= 9
    assert note.top > heading.top + heading.height and note.top + note.height <= int(0.95 * H)
    assert abs(note.left - heading.left) <= int(0.02 * W)
    if date is not None:
        assert date.top + date.height <= note.top
    assert by_name  # the slide is built


def test_formula_with_a_definition_in_words_sets_the_words_over_the_figures(env):
    s = OutlineSlide(id="w", kind=PatternKind.big_number, headline="Прибыль — разница выручки и расходов", content=SlideContent(formula="Прибыль = Выручка − Расходы = 900 000 − 780 000 = 120 000 ₽"))
    slide, _, _ = _render(env, s)
    words = _named(slide, "Formula words")
    figs = _named(slide, "Figure") + _named(slide, "Result figure")
    assert len(words) == 1 and _text(words[0]).split() == ["Прибыль", "=", "Выручка", "−", "Расходы"]
    assert len(figs) == 3 and all(words[0].top + words[0].height <= f.top + Emu(Pt(2)) for f in figs)
    fig_size = max(r.font.size.pt for r in figs[0].text_frame.paragraphs[0].runs)
    word_size = max(r.font.size.pt for p in words[0].text_frame.paragraphs for r in p.runs)
    assert word_size < fig_size


def test_two_pies_of_a_slide_share_one_legend_size_and_one_diameter(env):
    invest = ChartSpec(type="doughnut", title="Вложения", unit="₽", categories=["Витрина", "Лояльность", "Меню", "Обучение", "Резерв"], series=[InlineSeries(name="Вложения", values=[70000, 35000, 25000, 20000, 30000])])
    s = OutlineSlide(id="pp", kind=PatternKind.chart, headline="Выручка и вложения", content=SlideContent(chart=PIE, chart2=invest, bullets=["Кофе дает 60% выручки"]))
    slide, warnings, _ = _render(env, s)
    charts = [sh for sh in slide.shapes if sh.has_chart]
    assert len(charts) == 2 and abs(charts[0].width - charts[1].width) <= 2
    sizes = {r.font.size.pt for sh in _named(slide, "Legend") for p in sh.text_frame.paragraphs for r in p.runs}
    assert len(sizes) == 1
    assert len(_named(slide, "Swatch")) == 8


def test_charts_of_a_pair_without_titles_are_named_by_their_series(env):
    deck, manifest, ws = env
    reg = [Series(id="a", name="Средний чек", categories=["Сейчас", "Цель"], values=[300, 330], unit="₽"), Series(id="b", name="Доля чеков с едой", categories=["Сейчас", "Цель"], values=[20, 30], unit="%")]
    s = OutlineSlide(id="n", kind=PatternKind.chart, headline="Комбо поднимут средний чек на 10%", content=SlideContent(chart=ChartSpec(type="column", series_ids=["a"]), chart2=ChartSpec(type="column", series_ids=["b"])))
    outline = DeckOutline(title="T", series=reg, slides=[s])
    ps = LayoutSlide(outline_id="n", mode="synth", composition=composition_for(s))
    slide, _ = render_synth(DeckBuilder(deck), ps, s, manifest, ws, outline)
    titles = sorted(_named(slide, "Chart title"), key=lambda sh: sh.left)
    assert [_text(t) for t in titles] == ["Средний чек", "Доля чеков с едой"]


def test_a_before_after_chart_highlights_the_after_bar():
    from verstka.rendering.compose import _after_index

    o = DeckOutline(title="T")
    plain = BUYS.model_copy(update={"highlight_index": None})
    assert _after_index(plain, o) == 1
    assert _after_index(plain.model_copy(update={"categories": ["Кофе", "Чай"]}), o) is None
    assert _after_index(plain.model_copy(update={"highlight_index": 0}), o) == 0


def test_a_long_column_grows_its_card_and_draws_its_figure(env, tmp_path):
    """Two columns whose lists do not fit the area at any size: the cards grow with the text (never the text hanging
    below its card, as on the long brief's «Меры» column), a column's figure is drawn over its lines, and the audit
    finds no text outside its card."""
    from verstka.audit.checks.layout import text_outside_card
    from verstka.audit.ir import build_deck_ir
    from verstka.audit.registry import AuditContext

    long_lines = [f"Мера номер {i}: ежедневный учёт остатков и пересмотр закупочных цен у поставщиков" for i in range(1, 8)]
    s = OutlineSlide(id="c", kind=PatternKind.two_column, headline="Потери сократятся", takeaway="Списания — с 27 000 до 15 000 ₽", content=SlideContent(
        columns=[SlideItem(title="Меры", bullets=long_lines), SlideItem(title="Цель", number="22 770 ₽", bullets=["Экономия относительно уровня 35%"])],
        bullets=["Доля расходов на продукты: 35 → 33%", "Списания: 27 000 → 15 000 ₽"],
    ))
    slide, _, manifest = _render(env, s)
    cards = sorted(_named(slide, "Card"), key=lambda sh: sh.left)
    cols = sorted([sh for sh in slide.shapes if sh.name.rsplit(" ", 1)[0] == "Column"], key=lambda sh: sh.left)
    assert cards and cols
    for card, col in zip(cards, cols):
        assert col.top + col.height <= card.top + card.height + Emu(12700), (card.name, col.name)
    assert any("22 770" in _text(sh) for sh in cols)
    path = tmp_path / "cols.pptx"
    slide.part.package.save(str(path))
    issues = text_outside_card(AuditContext(ir=build_deck_ir(path), manifest=manifest))
    assert not [i for i in issues if i.severity == "error"], [i.message for i in issues]
